"""Pry v3 — Full-stack web intelligence API.
Scrape + Crawl + Automate + Parse + Extract + MCP
Self-hosted, free, better than Firecrawl."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pry.api.client import close_client
from pry.api.routers.ai.agency import router as agency_router
from pry.api.routers.ai.ai import router as ai_router
from pry.api.routers.ai.analysis import router as analysis_router
from pry.api.routers.commerce.commerce import router as commerce_router
from pry.api.routers.commerce.commerce_data import router as commerce_data_router
from pry.api.routers.commerce.costing import router as costing_router
from pry.api.routers.commerce.dashboard import router as dashboard_router
from pry.api.routers.commerce.marketplace import router as marketplace_router
from pry.api.routers.core.admin import router as admin_router
from pry.api.routers.core.auth import router as auth_router
from pry.api.routers.core.automation import router as automation_router
from pry.api.routers.core.batch import router as batch_router
from pry.api.routers.core.capabilities import router as capabilities_router
from pry.api.routers.core.circuit_breaker import router as circuit_breaker_router
from pry.api.routers.core.config import router as config_router
from pry.api.routers.core.diagnostics import router as diagnostics_router
from pry.api.routers.core.health import router as health_router
from pry.api.routers.data.attention import router as attention_router
from pry.api.routers.data.crypto_market import router as crypto_market_router
from pry.api.routers.data.enrichment import router as enrichment_router
from pry.api.routers.data.healthcare_data import router as healthcare_data_router
from pry.api.routers.data.intelligence import router as intelligence_router
from pry.api.routers.data.jobs import router as jobs_router
from pry.api.routers.data.legal_docs import router as legal_docs_router
from pry.api.routers.data.local_data import router as local_data_router
from pry.api.routers.integrations.alerts import router as alerts_router
from pry.api.routers.integrations.compliance import router as compliance_router
from pry.api.routers.integrations.email import router as email_router
from pry.api.routers.integrations.export import router as export_router
from pry.api.routers.integrations.gdpr import router as gdpr_router
from pry.api.routers.integrations.integrations import router as integrations_router
from pry.api.routers.scraping.advanced import router as advanced_router
from pry.api.routers.scraping.execute import router as execute_router
from pry.api.routers.scraping.extraction import router as extraction_router
from pry.api.routers.scraping.freshness import router as freshness_router
from pry.api.routers.user.crm import router as crm_router
from pry.commerce.pipeline import get_pipeline
from pry.core.deps import advanced, automator, extractor, queue, scraper
from pry.core.errors import (
    PryError,
)
from pry.core.middleware import (
    _AUTH_PUBLIC_PATHS,  # noqa: F401  (re-exported for compatibility)
    _LOOPBACK_OR_TEST_HOSTS,  # noqa: F401
    PryHttpMiddleware,
    _path_exists,  # noqa: F401
    is_loopback_client,  # noqa: F401
    request_authorized,  # noqa: F401  (imported by routers/proxy.py, routers/config.py)
)
from pry.core.observability import setup_tracing
from pry_mcp import make_fallback_server, register_all
from pry_mcp.app import create_mcp_app

# gov_data / ip_data routers land from parallel agents; import them guarded so
# api.py keeps working (and the x402 gates stay armed) before they arrive.
try:
    from pry.api.routers.data.gov_data import router as gov_data_router

    _GOV_DATA_ROUTER: Any | None = gov_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _GOV_DATA_ROUTER = None
try:
    from pry.api.routers.data.ip_data import router as ip_data_router

    _IP_DATA_ROUTER: Any | None = ip_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _IP_DATA_ROUTER = None
# climate_data / research_data routers land in this tree; import them guarded
# so api.py keeps working (and the x402 gates stay armed) if they have not
# landed yet.
try:
    from pry.api.routers.data.climate_data import router as climate_data_router

    _CLIMATE_DATA_ROUTER: Any | None = climate_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _CLIMATE_DATA_ROUTER = None
try:
    from pry.api.routers.data.research_data import router as research_data_router

    _RESEARCH_DATA_ROUTER: Any | None = research_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _RESEARCH_DATA_ROUTER = None
# events_data / freight_data / energy_data / food_data / supply_data routers
# land in this tree; import them guarded so api.py keeps working (and the
# x402 gates stay armed) if they have not landed yet.
try:
    from pry.api.routers.data.events_data import router as events_data_router

    _EVENTS_DATA_ROUTER: Any | None = events_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _EVENTS_DATA_ROUTER = None
try:
    from pry.api.routers.data.freight_data import router as freight_data_router

    _FREIGHT_DATA_ROUTER: Any | None = freight_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _FREIGHT_DATA_ROUTER = None
try:
    from pry.api.routers.data.energy_data import router as energy_data_router

    _ENERGY_DATA_ROUTER: Any | None = energy_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _ENERGY_DATA_ROUTER = None
try:
    from pry.api.routers.data.food_data import router as food_data_router

    _FOOD_DATA_ROUTER: Any | None = food_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _FOOD_DATA_ROUTER = None
try:
    from pry.api.routers.data.supply_data import router as supply_data_router

    _SUPPLY_DATA_ROUTER: Any | None = supply_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _SUPPLY_DATA_ROUTER = None
# app_store_data / news_data / compliance_data / deals_data routers land in
# this tree from parallel agents; import them guarded so api.py keeps working
# (and the x402 gates stay armed) if they have not landed yet.
try:
    from pry.api.routers.data.app_store_data import router as app_store_data_router

    _APP_STORE_DATA_ROUTER: Any | None = app_store_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _APP_STORE_DATA_ROUTER = None
try:
    from pry.api.routers.data.news_data import router as news_data_router

    _NEWS_DATA_ROUTER: Any | None = news_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _NEWS_DATA_ROUTER = None
try:
    from pry.api.routers.integrations.compliance_data import router as compliance_data_router

    _COMPLIANCE_DATA_ROUTER: Any | None = compliance_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _COMPLIANCE_DATA_ROUTER = None
try:
    from pry.api.routers.data.deals_data import router as deals_data_router

    _DEALS_DATA_ROUTER: Any | None = deals_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _DEALS_DATA_ROUTER = None
# bidding_data router lands from a parallel agent; import it guarded so
# api.py keeps working (and the x402 gates stay armed) before it arrives.
try:
    from pry.api.routers.data.bidding_data import router as bidding_data_router

    _BIDDING_DATA_ROUTER: Any | None = bidding_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _BIDDING_DATA_ROUTER = None
# billing_packs router (bulk scrape-credit crypto checkout) — guarded so
# api.py keeps working if the commerce module has not landed yet.
try:
    from pry.api.routers.commerce.billing_packs import router as billing_packs_router

    _BILLING_PACKS_ROUTER: Any | None = billing_packs_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _BILLING_PACKS_ROUTER = None
from pry.api.routers.ai.vision import router as vision_router
from pry.api.routers.commerce.reconciliation import router as reconciliation_router
from pry.api.routers.commerce.referrals import router as referrals_router
from pry.api.routers.commerce.reports import router as reports_router
from pry.api.routers.commerce.review import router as review_router
from pry.api.routers.commerce.training import router as training_router
from pry.api.routers.commerce.x402 import router as x402_router
from pry.api.routers.core.api_keys import router as api_keys_router
from pry.api.routers.core.proxy import router as proxy_router
from pry.api.routers.core.quality import router as quality_router
from pry.api.routers.core.sessions import router as sessions_router
from pry.api.routers.core.share import router as share_router
from pry.api.routers.core.signup import router as signup_router
from pry.api.routers.core.stats import router as stats_router
from pry.api.routers.core.system import router as system_router
from pry.api.routers.core.templates import router as templates_router
from pry.api.routers.core.well_known import router as well_known_router
from pry.api.routers.data.real_estate import router as real_estate_router
from pry.api.routers.data.sports_data import router as sports_data_router
from pry.api.routers.data.travel import router as travel_router
from pry.api.routers.integrations.monitoring import router as monitoring_router
from pry.api.routers.integrations.webhooks import router as webhooks_router
from pry.api.routers.scraping.parsing import router as parsing_router
from pry.api.routers.scraping.pipeline import router as pipeline_router
from pry.api.routers.scraping.pipelines import router as pipelines_router
from pry.api.routers.scraping.recorder import router as recorder_router
from pry.api.routers.scraping.scraping import router as scraping_router
from pry.api.routers.scraping.scraping_api import router as scraping_api_router
from pry.api.routers.scraping.seo import router as seo_router
from pry.api.routers.scraping.streams import router as streams_router
from pry.api.routers.scraping.structure import router as structure_router
from pry.api.routers.scraping.transform import router as transform_router
from pry.core.settings import settings
from pry.payments.crypto.router import router as crypto_payment_router
from pry.payments.x402_middleware import X402Middleware

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
    pass

# ── Init ──


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate deps. Shutdown: cleanup clients."""
    logger.info("pry_startup", version="3.0.0")
    setup_tracing()

    # x402 route-classification audit (fail-closed gate).
    # PRY_X402_AUDIT: strict (default) = raise on unclassified routes;
    # warn = log critical but boot; off = skip entirely.
    from pry.payments.x402_middleware import audit_route_classification

    _audit_mode = os.getenv("PRY_X402_AUDIT", "strict").strip().lower()
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
    get_pipeline()  # Initialize pipeline
    # Register DataBus bridge (publish scraped results to rmi-backend)
    import pry.api.databus_bridge  # noqa: F401 — auto-registers hook on import

    yield
    logger.info("pry_shutdown")
    await close_client()
    for obj in [scraper, automator, extractor, advanced, queue]:
        if hasattr(obj, "close"):
            with suppress(Exception):
                await obj.close()
    # Dispose DB engine/session pools (graceful shutdown).
    with suppress(Exception):
        from pry.core.db import dispose_engines

        dispose_engines()


app = FastAPI(
    title="Pry",
    version="3.0.0",
    description="Pry open any website. Web scraping + browser automation + document parsing. Self-hosted, free, better than Firecrawl.",
    lifespan=lifespan,
)

# ── MCP sub-app ──
# Built by pry_mcp.app.create_mcp_app(); mounted on /mcp so that streaming SSE
# endpoints bypass the main app's BaseHTTPMiddleware (which buffers response
# bodies and breaks SSE).
_mcp_server_instance: Any | None = None


def _get_mcp_server() -> Any:
    """Lazy-initialize the spec-compliant MCP server."""
    global _mcp_server_instance
    if _mcp_server_instance is None:
        _mcp_server_instance = make_fallback_server(base_url=f"http://localhost:{settings.port}")
        register_all(_mcp_server_instance)
    return _mcp_server_instance


# The lambda defers the _get_mcp_server lookup to request time, so tests that
# patch api._get_mcp_server keep working.
mcp_app = create_mcp_app(get_server=lambda: _get_mcp_server())

app.mount("/mcp", mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rugmunch.io",
        # Internal app origins are covered by the wildcard regex below —
        # do not enumerate internal hostnames in public source (TOP-100 #11).
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"https://.*\.rugmunch\.io",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gate paid endpoints behind x402 payments. Free endpoints are always public.


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(
                request_id=req_id,
                instance=str(request.url),
            ),
        )

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """RFC 7807 Problem Details for HTTP errors (404, 401, 403, etc)."""
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        status = exc.status_code
        titles = {
            "Bad Request": 400,
            "Unauthorized": 401,
            "Forbidden": 403,
            "Not Found": 404,
            "Conflict": 409,
            "Too Many Requests": 429,
            "Internal Server Error": 500,
            "Bad Gateway": 502,
            "Service Unavailable": 503,
        }
        title = {v: k for k, v in titles.items()}.get(status, "Error")
        return JSONResponse(
            status_code=status,
            content={
                "type": "/errors/" + title.lower().replace(" ", "-")
                if status != 500
                else "about:blank",
                "title": title,
                "status": status,
                "detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "request_id": req_id,
                "instance": str(request.url),
                "timestamp": datetime.now(UTC).isoformat(),
                "code": title.lower().replace(" ", "_"),
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        logger.exception("unhandled_exception", extra={"request_id": req_id})

        return JSONResponse(
            status_code=500,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred",
                "request_id": req_id,
                "instance": str(request.url),
                "timestamp": datetime.now(UTC).isoformat(),
                "code": "internal_error",
            },
        )


add_error_handlers(app)

# Auth + rate limiting + timing middleware (see middleware.py).
app.add_middleware(PryHttpMiddleware)

# Classification lives in x402_middleware (DEFAULT_FREE_PATHS / PAID_ENDPOINTS)
# and is audited at startup by the lifespan hook below — fail-closed.
# ORDER MATTERS: X402Middleware is added AFTER PryHttpMiddleware so it sits
# OUTERMOST — a keyless agent must reach the 402 challenge BEFORE the
# API-key auth layer rejects with 401. Verified payments mark
# scope["x402_verified"], which request_authorized accepts as the credential.
app.add_middleware(X402Middleware)


# ── Routers ──

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(healthcare_data_router)
app.include_router(scraping_router)
app.include_router(templates_router)
app.include_router(ai_router)
app.include_router(admin_router)
app.include_router(advanced_router)
app.include_router(agency_router)
app.include_router(alerts_router)
app.include_router(analysis_router)
app.include_router(automation_router)
app.include_router(batch_router)
app.include_router(crm_router)
app.include_router(crypto_market_router)
app.include_router(circuit_breaker_router)
app.include_router(commerce_router)
app.include_router(commerce_data_router)
app.include_router(compliance_router)
app.include_router(capabilities_router)
app.include_router(config_router)
app.include_router(costing_router)
app.include_router(dashboard_router)
app.include_router(diagnostics_router)
app.include_router(email_router)
app.include_router(enrichment_router)
app.include_router(execute_router)
app.include_router(export_router)
app.include_router(extraction_router)
app.include_router(freshness_router)
app.include_router(attention_router)
app.include_router(gdpr_router)
app.include_router(integrations_router)
app.include_router(intelligence_router)
app.include_router(jobs_router)
app.include_router(legal_docs_router)
app.include_router(local_data_router)
app.include_router(marketplace_router)
# gov_data / ip_data routers are included when their modules have landed.
if _GOV_DATA_ROUTER is not None:
    app.include_router(_GOV_DATA_ROUTER)
if _IP_DATA_ROUTER is not None:
    app.include_router(_IP_DATA_ROUTER)
# climate_data / research_data routers are included when they have landed.
if _CLIMATE_DATA_ROUTER is not None:
    app.include_router(_CLIMATE_DATA_ROUTER)
if _RESEARCH_DATA_ROUTER is not None:
    app.include_router(_RESEARCH_DATA_ROUTER)
# events_data / freight_data / energy_data / food_data / supply_data routers
# are included when they have landed.
if _EVENTS_DATA_ROUTER is not None:
    app.include_router(_EVENTS_DATA_ROUTER)
if _FREIGHT_DATA_ROUTER is not None:
    app.include_router(_FREIGHT_DATA_ROUTER)
if _ENERGY_DATA_ROUTER is not None:
    app.include_router(_ENERGY_DATA_ROUTER)
if _FOOD_DATA_ROUTER is not None:
    app.include_router(_FOOD_DATA_ROUTER)
if _SUPPLY_DATA_ROUTER is not None:
    app.include_router(_SUPPLY_DATA_ROUTER)
# app_store_data / news_data / compliance_data / deals_data routers are
# included when they have landed.
if _APP_STORE_DATA_ROUTER is not None:
    app.include_router(_APP_STORE_DATA_ROUTER)
if _NEWS_DATA_ROUTER is not None:
    app.include_router(_NEWS_DATA_ROUTER)
if _COMPLIANCE_DATA_ROUTER is not None:
    app.include_router(_COMPLIANCE_DATA_ROUTER)
if _DEALS_DATA_ROUTER is not None:
    app.include_router(_DEALS_DATA_ROUTER)
# bidding_data router is included when it has landed.
if _BIDDING_DATA_ROUTER is not None:
    app.include_router(_BIDDING_DATA_ROUTER)
# billing_packs router is included when it has landed.
if _BILLING_PACKS_ROUTER is not None:
    app.include_router(_BILLING_PACKS_ROUTER)
app.include_router(monitoring_router)
app.include_router(parsing_router)
app.include_router(pipeline_router)
app.include_router(real_estate_router)
app.include_router(travel_router)
app.include_router(pipelines_router)
app.include_router(proxy_router)
app.include_router(quality_router)
app.include_router(reconciliation_router)
app.include_router(recorder_router)
app.include_router(referrals_router)
app.include_router(reports_router)
app.include_router(review_router)
app.include_router(seo_router)
app.include_router(scraping_api_router)
app.include_router(sessions_router)
app.include_router(share_router)
app.include_router(signup_router)
app.include_router(well_known_router)
app.include_router(sports_data_router)
app.include_router(stats_router)
app.include_router(structure_router)
app.include_router(system_router)
app.include_router(training_router)
app.include_router(transform_router)
app.include_router(streams_router)
app.include_router(api_keys_router)
app.include_router(vision_router)
app.include_router(webhooks_router)
app.include_router(x402_router)
app.include_router(crypto_payment_router)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
