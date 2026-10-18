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


def _startup_telemetry(app: FastAPI) -> None:
    """Gated: no-op unless OTEL_ENABLED / OTLP endpoint is set."""
    from pry.core.otel_setup import setup_telemetry

    setup_telemetry(app)


def _startup_db() -> None:
    # Create database tables (moved from get_engine to avoid per-request DDL).
    try:
        from pry.core.db.session import init_db

        init_db()
    except Exception as e:  # noqa: BLE001 — alembic may own the schema
        logger.warning("pry_init_db_skipped", extra={"error": str(e)[:200]})


def _audit_x402(app: FastAPI) -> None:
    """Fail-closed route-classification audit; skipped when x402 is disabled."""
    from pry.api.kill_switches import X402_ENABLED
    from pry.payments.x402_middleware import audit_route_classification

    mode = os.getenv("PRY_X402_AUDIT", "strict").strip().lower()
    if not X402_ENABLED:
        logger.info("x402_disabled_audit_skipped", reason="PRY_X402_ENABLED=false")
        return
    if mode == "off":
        return
    unclassified = audit_route_classification(app)
    if not unclassified:
        logger.info("x402_audit_clean")
        return
    if mode == "warn":
        logger.critical(
            "x402_audit_unclassified_routes",
            extra={"count": len(unclassified), "paths": unclassified[:20]},
        )
        return
    detail = ", ".join(unclassified[:20]) + (" …" if len(unclassified) > 20 else "")
    raise RuntimeError(
        "x402 route classification audit failed — every route must be "
        f"explicitly free or paid. Unclassified ({len(unclassified)}): {detail}"
    )


def _warn_if_no_api_key() -> None:
    if settings.api_key:
        return
    logger.warning(
        "pry_api_key_unset",
        message=(
            "PRY_API_KEY is not set; protected endpoints are loopback-only "
            "(remote requests get 401). Set a strong key to allow remote clients."
        ),
    )


def _startup_services() -> None:
    from pry.commerce.pipeline import get_pipeline

    get_pipeline()  # Initialize pipeline
    # Register DataBus bridge (publish scraped results to rmi-backend)
    import pry.api.databus_bridge  # noqa: F401 — auto-registers hook on import


async def _close_all() -> None:
    with suppress(Exception):
        from pry.core.otel_setup import shutdown_telemetry

        shutdown_telemetry()
    await close_client()
    # Close pooled browsers so they don't leak on process exit. Lazy imports
    # avoid the engine→api transitive boundary violation in import-linter.
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
    with suppress(Exception):
        from pry.core.db import dispose_engines

        dispose_engines()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate deps. Shutdown: cleanup clients."""
    logger.info("pry_startup", version="3.0.0")
    _startup_telemetry(app)
    _startup_db()
    _audit_x402(app)
    _warn_if_no_api_key()
    _startup_services()
    yield
    logger.info("pry_shutdown")
    await _close_all()
