# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Observability: Prometheus metrics, OpenTelemetry tracing, structured logging.

Metric definitions live in ``pry.core.metrics_defs``, collectors/summaries in
``pry.core.metrics_collectors``, tracking helpers in
``pry.core.metrics_tracking``. They are re-exported here so the historic
``pry.core.observability.<name>`` import surface is unchanged.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from pry.core.metrics_collectors import (
    QUEUE_DEPTH_NAME,
    QUEUE_OLDEST_JOB_AGE_NAME,
    JobQueueCollector,
    _sample,
    get_metrics_output,
    metrics_summary,
    metrics_summary_text,
)
from pry.core.metrics_defs import (
    ACTIVE_CONNECTIONS,
    ACTIVE_SESSIONS,
    CACHE_HITS,
    ERROR_COUNT,
    LLM_CALLS,
    LLM_COST,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    SCRAPE_COUNT,
    SCRAPE_LATENCY,
    TEMPLATE_USAGE,
    _has_prometheus,
)
from pry.core.metrics_tracking import (
    session_ended,
    session_started,
    track_llm_call,
    track_request,
    track_scrape,
    track_template,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


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
        for key, value in (attributes or {}).items():
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


__all__ = [
    "ACTIVE_CONNECTIONS",
    "ACTIVE_SESSIONS",
    "CACHE_HITS",
    "ERROR_COUNT",
    "LLM_CALLS",
    "LLM_COST",
    "QUEUE_DEPTH_NAME",
    "QUEUE_OLDEST_JOB_AGE_NAME",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "SCRAPE_COUNT",
    "SCRAPE_LATENCY",
    "TEMPLATE_USAGE",
    "JobQueueCollector",
    "_has_prometheus",
    "_sample",
    "get_metrics_output",
    "get_tracer",
    "metrics_summary",
    "metrics_summary_text",
    "session_ended",
    "session_started",
    "set_span_attributes",
    "setup_tracing",
    "span",
    "track_llm_call",
    "track_request",
    "track_scrape",
    "track_template",
]
