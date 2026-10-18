"""App lifecycle — structured logging setup and the FastAPI lifespan hook.

Split out of api.py (god-file split, 2026-09).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from pry.api.client import close_client
from pry.core.deps import advanced, automator, extractor, queue, scraper
from pry.core.settings import settings

# Configure structured (JSON) logging for the whole process. Per
# CONVENTIONS.md Part 5, all Pry logs must be JSON with timestamp, level,
# service, and event. setup_logging() bridges stdlib logging through
# structlog so that any logger.info("event", k=v) becomes a JSON record.
try:
    from pry.core.logging_config import get_logger as _get_logger, setup_logging

    setup_logging()
    logger = _get_logger(__name__)
except ImportError:
    # logging_config not available (e.g., minimal install); use stdlib
    import logging

    logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate deps. Shutdown: cleanup clients."""
    logger.info("pry_startup", version="3.0.0")
    # Gated: no-op unless OTEL_ENABLED / OTEL_EXPORTER_OTLP_ENDPOINT is set.
    # Batch export means an unreachable collector never blocks startup.
    from pry.core.otel_setup import setup_telemetry

    setup_telemetry(app)

    # Create database tables (moved from get_engine to avoid per-request DDL).
    try:
        from pry.core.db.session import init_db

        init_db()
    except Exception as e:  # noqa: BLE001 — DB init failure is non-fatal (alembic may handle it)
        logger.warning("pry_init_db_skipped", extra={"error": str(e)[:200]})

    # x402 route-classification audit (fail-closed gate).
    # PRY_X402_AUDIT: strict (default) = raise on unclassified routes;
    # warn = log critical but boot; off = skip entirely.
    #
    # The audit exists to protect the payment gate, so it is meaningless when
    # that gate is not installed. PRY_X402_ENABLED=false (the self-host
    # default) must not fail boot over paid/free classification — a self-hoster
    # with no payee has no gate to misconfigure.
    from pry.api.kill_switches import X402_ENABLED
    from pry.payments.x402_middleware import audit_route_classification

    _audit_mode = os.getenv("PRY_X402_AUDIT", "strict").strip().lower()
    if not X402_ENABLED:
        _audit_mode = "off"
        logger.info("x402_disabled_audit_skipped", reason="PRY_X402_ENABLED=false")
    if _audit_mode != "off":
        _unclassified = audit_route_classification(app)
        if _unclassified:
            if _audit_mode == "warn":
                logger.critical(
                    "x402_audit_unclassified_routes",
                    extra={"count": len(_unclassified), "paths": _unclassified[:20]},
                )
            else:
                raise RuntimeError(
                    "x402 route classification audit failed — every route must be "
                    f"explicitly free or paid. Unclassified ({len(_unclassified)}): "
                    + ", ".join(_unclassified[:20])
                    + (" …" if len(_unclassified) > 20 else "")
                )
        else:
            logger.info("x402_audit_clean")

    if not settings.api_key:
        logger.warning(
            "pry_api_key_unset",
            message=(
                "PRY_API_KEY is not set; protected endpoints are loopback-only "
                "(remote requests get 401). Set a strong key to allow remote clients."
            ),
        )
    from pry.commerce.pipeline import get_pipeline

    get_pipeline()  # Initialize pipeline
    # Register DataBus bridge (publish scraped results to rmi-backend)
    import pry.api.databus_bridge  # noqa: F401 — auto-registers hook on import

    yield
    logger.info("pry_shutdown")
    with suppress(Exception):
        from pry.core.otel_setup import shutdown_telemetry

        shutdown_telemetry()
    await close_client()
    # Close pooled browsers (Playwright / undetected-chromedriver / Camoufox)
    # so they don't leak on process exit. Lazy import avoids engine→api
    # transitive boundary violation in import-linter.
    with suppress(Exception):
        from pry.engine.ultimate_scraper import close_browsers

        await close_browsers()
    with suppress(Exception):
        from pry.engine.camoufox_integration import close_browsers as _close_camoufox

        await _close_camoufox()
    for obj in [scraper, automator, extractor, advanced, queue]:
        if hasattr(obj, "close"):
            with suppress(Exception):
                await obj.close()
    # Dispose DB engine/session pools (graceful shutdown).
    with suppress(Exception):
        from pry.core.db import dispose_engines

        dispose_engines()
