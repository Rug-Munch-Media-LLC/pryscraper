# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Observability: Prometheus metrics, OpenTelemetry tracing, structured logging."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

# Prometheus + OpenTelemetry are hard runtime dependencies (see ACTOR_RUNTIME_PACKAGES).
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_has_prometheus = True
_has_otel = True

# OTLP exporter is an optional extra; guarded at the use site.
try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: F401
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace.export.batch import BatchSpanProcessor  # noqa: F401
except ImportError:
    # Optional OTLP extra is not installed: tracing still works through the
    # console exporter — an expected state, not an error.
    logger.debug("otlp_exporter_unavailable")
    _has_otlp = False
else:
    _has_otlp = True


# Metrics: each name is a Counter/Histogram/Gauge, or None when
# prometheus_client is unavailable (the else-branch below).
if _has_prometheus:
    REQUEST_COUNT = Counter(
        "pry_requests_total", "Total requests", ["method", "endpoint", "status"]
    )
    REQUEST_LATENCY = Histogram("pry_request_duration_seconds", "Request latency", ["endpoint"])
    ERROR_COUNT = Counter("pry_request_errors_total", "Request errors", ["method", "endpoint"])
    SCRAPE_COUNT = Counter("pry_scrapes_total", "Total scrapes", ["method", "status"])
    SCRAPE_LATENCY = Histogram("pry_scrape_duration_seconds", "Scrape latency", ["method"])
    LLM_CALLS = Counter("pry_llm_calls_total", "Total LLM calls", ["provider", "model"])
    LLM_COST = Counter("pry_llm_cost_usd_total", "Total LLM cost in USD", ["provider"])
    TEMPLATE_USAGE = Counter("pry_template_usage_total", "Template usage", ["template_id"])
    CACHE_HITS = Counter("pry_cache_hits_total", "Cache hits", ["cache_type"])
    ACTIVE_CONNECTIONS = Gauge("pry_active_connections", "Active connections", ["type"])
    ACTIVE_SESSIONS = Gauge(
        "pry_active_sessions",
        "Active scraping/browser sessions (bounded by PRY_MAX_SESSIONS)",
        ["type"],
    )
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None
    ERROR_COUNT = None
    SCRAPE_COUNT = None
    SCRAPE_LATENCY = None
    LLM_CALLS = None
    LLM_COST = None
    TEMPLATE_USAGE = None
    CACHE_HITS = None
    ACTIVE_CONNECTIONS = None
    ACTIVE_SESSIONS = None

# Batch-queue SLIs. A plain Gauge would emit nothing until a caller set it —
# and there is no such caller, so the panel would exist but never fill. A
# collector instead samples the in-process queue at scrape time: always
# fresh, no background thread, no Redis round-trip.
QUEUE_DEPTH_NAME = "pry_queue_depth"
QUEUE_OLDEST_JOB_AGE_NAME = "pry_queue_oldest_job_age_seconds"


class JobQueueCollector:
    """Emit batch-queue depth and oldest-job age from ``deps.queue``.

    Reads only the local LRU (same source as ``/health``'s ``queue_depth``),
    so it never blocks a scrape on Redis. Structural errors degrade to no
    series rather than a fabricated zero: a missing queue means "unknown",
    not "empty".
    """

    def collect(self):  # type: ignore[no-untyped-def]
        depth = GaugeMetricFamily(
            QUEUE_DEPTH_NAME, "Batch jobs pending or running (local queue)", labels=["source"]
        )
        age = GaugeMetricFamily(
            QUEUE_OLDEST_JOB_AGE_NAME,
            "Age in seconds of the oldest pending/running batch job",
            labels=["source"],
        )
        try:
            from pry.core.deps import queue

            jobs = getattr(queue, "_local_jobs", None)
            if not isinstance(jobs, dict):
                return
            active = [
                j
                for j in list(jobs.values())
                if isinstance(j, dict) and j.get("status") in ("pending", "running")
            ]
            depth.add_metric(["local"], len(active))
            oldest = 0.0
            for job in active:
                try:
                    created = job.get("created_at")
                    ts = time.time()
                    if created:
                        ts = datetime.fromisoformat(str(created)).timestamp()
                    oldest = max(oldest, max(0.0, time.time() - ts))
                except (TypeError, ValueError):
                    continue
            age.add_metric(["local"], oldest)
        except Exception:  # noqa: BLE001 — metrics must never break a scrape
            logger.debug("queue_metrics_unavailable")
            return
        yield depth
        yield age


if _has_prometheus:
    try:
        REGISTRY.register(JobQueueCollector())
    except (ValueError, TypeError):  # pragma: no cover — already registered
        logger.debug("queue_collector_already_registered")


def setup_tracing(service_name: str = "pry") -> None:
    """Deprecated alias for :func:`pry.core.otel_setup.setup_telemetry`.

    Kept so existing callers (lifespan, tests) keep working. Delegation means
    tracing is a no-op unless ``OTEL_ENABLED`` or an OTLP endpoint is set.
    """
    from pry.core.otel_setup import setup_telemetry

    setup_telemetry(service_name=service_name)


_TRACER: Any = None


def get_tracer(name: str = "pry") -> Any:
    """Return a tracer, or None when OTel is unavailable.

    Callers must treat None as 'tracing disabled' — see ``span()`` for the
    contextmanager that handles both cases.
    """
    global _TRACER
    if not _has_otel:
        return None
    if _TRACER is None:
        try:
            _TRACER = trace.get_tracer(name)
        except Exception:
            logger.warning("observability_exception_handler", exc_info=True)
            _TRACER = None
    return _TRACER


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Start a span when tracing is active; no-op context otherwise.

    Usage:
        with span("scrape.tier", {"tier": name}):
            ...
    Exceptions propagate unchanged; they are recorded on the span (status +
    exception event) before re-raise so downstream exporters see failures.
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as otel_span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    otel_span.set_attribute(key, value)
        try:
            yield otel_span
        except Exception as exc:
            otel_span.record_exception(exc)
            from opentelemetry.trace import Status, StatusCode

            otel_span.set_status(Status(StatusCode.ERROR, str(exc)[:120]))
            raise


def set_span_attributes(attributes: dict[str, Any]) -> None:
    """Attach attributes to the CURRENT active span (no-op when tracing off).

    Used by middleware to record status/duration on the request span opened
    by ``span()`` — the span object itself is not passed down the ASGI chain.
    """
    tracer = get_tracer()
    if tracer is None:
        return
    try:
        current = trace.get_current_span()
        if current is None or not getattr(current, "is_recording", lambda: False)():
            return
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
    except Exception:  # noqa: BLE001 — tracing must never break serving
        logger.debug("span_attribute_failed")


@contextmanager
def track_request(endpoint: str, method: str = "GET") -> Iterator[None]:
    """Context manager to track request metrics and timing.

    Increments ``pry_requests_total`` (with status) and observes
    ``pry_request_duration_seconds``. When the wrapped code raises, also
    increments ``pry_request_errors_total`` for the endpoint so error
    rate by endpoint = errors / requests.
    """
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.time() - start
        if _has_prometheus and REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
            if status == "error" and ERROR_COUNT:
                ERROR_COUNT.labels(method=method, endpoint=endpoint).inc()


@contextmanager
def track_scrape(method: str = "direct") -> Iterator[None]:
    """Context manager to track scrape metrics."""
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.time() - start
        if _has_prometheus and SCRAPE_COUNT and SCRAPE_LATENCY:
            SCRAPE_COUNT.labels(method=method, status=status).inc()
            SCRAPE_LATENCY.labels(method=method).observe(elapsed)


def session_started(session_type: str = "browser") -> None:
    """Record that a scraping/browser session started (active gauge += 1)."""
    if _has_prometheus and ACTIVE_SESSIONS:
        ACTIVE_SESSIONS.labels(type=session_type).inc()


def session_ended(session_type: str = "browser") -> None:
    """Record that a scraping/browser session ended (active gauge -= 1)."""
    if _has_prometheus and ACTIVE_SESSIONS:
        ACTIVE_SESSIONS.labels(type=session_type).dec()


def track_llm_call(provider: str, model: str, cost: float = 0.0) -> None:
    if _has_prometheus and LLM_CALLS and LLM_COST:
        LLM_CALLS.labels(provider=provider, model=model).inc()
        if cost > 0:
            LLM_COST.labels(provider=provider).inc(cost)


def track_template(template_id: str) -> None:
    if _has_prometheus and TEMPLATE_USAGE:
        TEMPLATE_USAGE.labels(template_id=template_id).inc()


# Only these structural errors degrade a metric read to 0; anything else
# propagates so a broken read is never mistaken for a real zero counter.
_SAMPLE_ERRORS = (AttributeError, IndexError, TypeError, ValueError)


def _sample(name: str, metric: Any) -> int:
    """Best-effort read of a counter/gauge's total value from its samples.

    Excludes the synthetic ``<name>_created`` sample prometheus_client
    adds to counters (its value is a Unix timestamp, not a count).

    Structural errors degrade to 0 (see _SAMPLE_ERRORS); anything else
    propagates, because a failure rendered as 0 is indistinguishable from
    "the counter really is zero" — a false all-clear for operator-facing
    request/error totals, and a bogus derived error_rate_pct.
    """
    if metric is None:
        return 0
    try:
        return int(
            sum(s.value for s in metric.collect()[0].samples if not s.name.endswith("_created"))
        )
    except _SAMPLE_ERRORS:
        logger.warning("observability_exception_handler", exc_info=True)
        return 0


def metrics_summary() -> dict[str, Any]:
    """Return a dict of key counters for a human-facing /metrics summary.

    Values are best-effort (0 when prometheus_client is unavailable or a
    metric has no samples yet). This is intentionally cheap — it reads
    registered metric samples, it does not call generate_latest().
    """
    return {
        "requests_total": _sample("pry_requests_total", REQUEST_COUNT),
        "request_errors_total": _sample("pry_request_errors_total", ERROR_COUNT),
        "error_rate_pct": (
            round(
                100.0
                * _sample("pry_request_errors_total", ERROR_COUNT)
                / max(1, _sample("pry_requests_total", REQUEST_COUNT)),
                2,
            )
        ),
        "active_sessions": _sample("pry_active_sessions", ACTIVE_SESSIONS),
        "active_connections": _sample("pry_active_connections", ACTIVE_CONNECTIONS),
        "scrapes_total": _sample("pry_scrapes_total", SCRAPE_COUNT),
        "llm_calls_total": _sample("pry_llm_calls_total", LLM_CALLS),
        "llm_cost_usd_total": _sample("pry_llm_cost_usd_total", LLM_COST),
        "cache_hits_total": _sample("pry_cache_hits_total", CACHE_HITS),
        "template_usage_total": _sample("pry_template_usage_total", TEMPLATE_USAGE),
    }


def metrics_summary_text() -> str:
    """Plain-text summary of key counters (for /metrics/summary or logs)."""
    data = metrics_summary()
    lines = ["pry metrics summary"]
    for key, value in data.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def get_metrics_output() -> tuple[bytes, str]:
    """Return Prometheus metrics in text format."""
    if not _has_prometheus:
        return b"# Prometheus not installed\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
