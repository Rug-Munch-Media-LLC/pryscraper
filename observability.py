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
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# Try to import Prometheus
try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    _has_prometheus = True
except ImportError:
    _has_prometheus = False

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

# Try to import OpenTelemetry
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        ConsoleSpanExporter,
        SimpleSpanProcessor,
        SpanExporter,
        SpanProcessor,
    )

    # OTLP exporter is optional (install opentelemetry-exporter-otlp-proto-http)
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        _has_otlp = True
    except ImportError:
        _has_otlp = False

    _has_otel = True
except ImportError:
    _has_otel = False
    _has_otlp = False


# Metrics
# Declare metrics as Counter | None so mypy allows None assignment when prometheus is unavailable.
# At runtime, these are either Counter/Histogram/Gauge objects or None.
REQUEST_COUNT: Counter | None
REQUEST_LATENCY: Histogram | None
SCRAPE_COUNT: Counter | None
SCRAPE_LATENCY: Histogram | None
LLM_CALLS: Counter | None
LLM_COST: Counter | None
TEMPLATE_USAGE: Counter | None
CACHE_HITS: Counter | None
ACTIVE_CONNECTIONS: Gauge | None

if _has_prometheus:
    REQUEST_COUNT = Counter(
        "pry_requests_total", "Total requests", ["method", "endpoint", "status"]
    )
    REQUEST_LATENCY = Histogram("pry_request_duration_seconds", "Request latency", ["endpoint"])
    SCRAPE_COUNT = Counter("pry_scrapes_total", "Total scrapes", ["method", "status"])
    SCRAPE_LATENCY = Histogram("pry_scrape_duration_seconds", "Scrape latency", ["method"])
    LLM_CALLS = Counter("pry_llm_calls_total", "Total LLM calls", ["provider", "model"])
    LLM_COST = Counter("pry_llm_cost_usd_total", "Total LLM cost in USD", ["provider"])
    TEMPLATE_USAGE = Counter("pry_template_usage_total", "Template usage", ["template_id"])
    CACHE_HITS = Counter("pry_cache_hits_total", "Cache hits", ["cache_type"])
    ACTIVE_CONNECTIONS = Gauge("pry_active_connections", "Active connections", ["type"])
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY = None
    SCRAPE_COUNT = None
    SCRAPE_LATENCY = None
    LLM_CALLS = None
    LLM_COST = None
    TEMPLATE_USAGE = None
    CACHE_HITS = None
    ACTIVE_CONNECTIONS = None


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


@contextmanager
def track_request(endpoint: str, method: str = "GET"):
    """Context manager to track request metrics and timing."""
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


def track_llm_call(provider: str, model: str, cost: float = 0.0) -> None:
    if _has_prometheus and LLM_CALLS and LLM_COST:
        LLM_CALLS.labels(provider=provider, model=model).inc()
        if cost > 0:
            LLM_COST.labels(provider=provider).inc(cost)


def track_template(template_id: str) -> None:
    if _has_prometheus and TEMPLATE_USAGE:
        TEMPLATE_USAGE.labels(template_id=template_id).inc()


def get_metrics_output() -> tuple[bytes, str]:
    """Return Prometheus metrics in text format."""
    if not _has_prometheus:
        return b"# Prometheus not installed\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
