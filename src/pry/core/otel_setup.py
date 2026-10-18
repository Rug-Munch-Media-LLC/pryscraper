# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — OpenTelemetry bootstrap (gated, idempotent, non-blocking).

Activation contract
-------------------
* No ``OTEL_ENABLED`` (truthy) and no ``OTEL_EXPORTER_OTLP_ENDPOINT`` -> no-op.
  Nothing is registered, no provider is installed, no exporter is created.
* ``OTEL_ENABLED=1`` with an endpoint -> OTLP/HTTP via ``BatchSpanProcessor``.
  Batching means startup never waits on a collector: an unreachable endpoint
  fills the bounded queue and drops spans instead of blocking the process.
* ``OTEL_ENABLED=1`` without an endpoint -> console exporter (dev only).

Instrumentation (FastAPI, httpx) is best-effort: the instrumentation
packages are optional extras, so a missing module or a version mismatch
degrades to "not instrumented" rather than failing boot.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_initialised = False


def is_enabled() -> bool:
    """Return True when tracing should be initialised."""
    if os.getenv("OTEL_ENABLED", "").strip().lower() in _TRUTHY:
        return True
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def _build_provider(service_name: str) -> Any:
    """Build a TracerProvider with the configured exporter, or None."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": os.getenv("PRY_APP_VERSION", "3.0.0"),
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        logger.info("otel_exporter_console", extra={"service": service_name})
        return provider

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint),
                max_queue_size=2048,
                schedule_delay_millis=5000,
                export_timeout_millis=5000,
            )
        )
        logger.info("otel_exporter_otlp", extra={"service": service_name})
    except ImportError:
        # Endpoint configured but the OTLP extra is absent: keep serving
        # without spans instead of failing startup.
        logger.warning("otel_otlp_extra_missing", extra={"service": service_name})
        return None
    return provider


def _instrument(app: Any) -> None:
    """Best-effort FastAPI + httpx instrumentation."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # noqa: BLE001 — optional extra, never fatal
        logger.debug("otel_httpx_instrumentation_unavailable")
    if app is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,healthz,live,ready,readyz")
    except Exception:  # noqa: BLE001 — optional extra, never fatal
        logger.debug("otel_fastapi_instrumentation_unavailable")


def setup_telemetry(app: Any = None, service_name: str = "pry") -> bool:
    """Initialise OTel once. Returns True when tracing is active.

    Never raises: an exporter/instrumentation failure degrades to False so
    the API keeps serving. Safe to call more than once (idempotent).
    """
    global _initialised
    if _initialised:
        return True
    if not is_enabled():
        logger.debug("otel_disabled")
        return False
    try:
        from opentelemetry import trace

        provider = _build_provider(service_name)
        if provider is None:
            return False
        trace.set_tracer_provider(provider)
        _instrument(app)
        _initialised = True
        return True
    except Exception as exc:  # noqa: BLE001 — telemetry must never break boot
        logger.warning("otel_init_failed", extra={"error": type(exc).__name__})
        return False


def shutdown_telemetry() -> None:
    """Flush and shut the provider down (best-effort, bounded)."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception:  # noqa: BLE001 — shutdown must never raise
        logger.debug("otel_shutdown_failed")


__all__ = ["is_enabled", "setup_telemetry", "shutdown_telemetry"]
