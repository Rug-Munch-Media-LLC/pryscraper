# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Observability: Prometheus metrics, OpenTelemetry tracing, structured logging."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanProcessor,  # type: ignore[attr-defined]
)

# Prometheus + OpenTelemetry are hard runtime dependencies
# (see ACTOR_RUNTIME_PACKAGES in actor_factory.publish).
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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

    _has_otlp = True
except ImportError:
    _has_otlp = False

_has_otel = True


# Metrics
# Declare metrics as Counter | None so mypy allows None assignment when prometheus is unavailable.
# At runtime, these are either Counter/Histogram/Gauge objects or None.
REQUEST_COUNT: Counter | None
REQUEST_LATENCY: Histogram | None
ERROR_COUNT: Counter | None
SCRAPE_COUNT: Counter | None
SCRAPE_LATENCY: Histogram | None
LLM_CALLS: Counter | None
LLM_COST: Counter | None
TEMPLATE_USAGE: Counter | None
CACHE_HITS: Counter | None
ACTIVE_CONNECTIONS: Gauge | None
ACTIVE_SESSIONS: Gauge | None

if _has_prometheus:
    REQUEST_COUNT = Counter(
        "pry_requests_total", "Total requests", ["method", "endpoint", "status"]
    )
    REQUEST_LATENCY = Histogram("pry_request_duration_seconds", "Request latency", ["endpoint"])
    ERROR_COUNT = Counter(
        "pry_request_errors_total",
        "Request errors by endpoint",
        ["method", "endpoint"],
    )
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


def setup_tracing(service_name: str = "pry") -> None:
    """Initialize OpenTelemetry tracing.

    Uses OTLP HTTP exporter if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set
    and the OTLP package is installed. Falls back to console export.
    """
    if not _has_otel:
        return
    try:
        provider = TracerProvider()
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        exporter: SpanExporter
        processor: SpanProcessor
        if otlp_endpoint and _has_otlp:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export.batch import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            processor = BatchSpanProcessor(exporter)
            logger.info("tracing_otlp", extra={"endpoint": otlp_endpoint})
        else:
            exporter = ConsoleSpanExporter()
            processor = SimpleSpanProcessor(exporter)
            logger.info("tracing_console", extra={"service": service_name})
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
    except Exception as e:  # noqa: BLE001
        logger.warning("tracing_init_failed", extra={"error": str(e)[:80]})


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
        except Exception:  # noqa: BLE001 — tracing must never break scraping
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
def track_request(endpoint: str, method: str = "GET"):
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
def track_scrape(method: str = "direct"):
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


def _sample(name: str, metric: Any) -> int:
    """Best-effort read of a counter/gauge's total value from its samples.

    Excludes the synthetic ``<name>_created`` sample prometheus_client
    adds to counters (its value is a Unix timestamp, not a count).
    """
    if metric is None:
        return 0
    try:
        return int(
            sum(s.value for s in metric.collect()[0].samples if not s.name.endswith("_created"))
        )
    except Exception:  # noqa: BLE001 - metric sampling must never break /metrics
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
