"""App factory — builds the Pry FastAPI application.

Split out of api.py (god-file split, 2026-09). Exposes the assembled ``app``
plus the x402 V2 spec endpoints (``/supported``, ``/readyz``, ``/metrics``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pry.api.exception_handlers import add_error_handlers
from pry.api.kill_switches import MCP_ENABLED, X402_ENABLED
from pry.api.lifecycle import lifespan
from pry.api.router_registry import register_routers
from pry.core.middleware import PryHttpMiddleware
from pry.core.settings import settings
from pry.payments.x402_middleware import X402Middleware

app = FastAPI(
    title="PryScraper API",
    version="3.0.0",
    description=(
        "PryScraper is a self-hosted web scraping + browser automation platform. "
        "Scrape, crawl, parse and extract structured data from any website with a "
        "10-tier anti-bot fallback system, then monetize paid operations with x402 "
        "micropayments (pay-per-scrape over HTTP 402). Free endpoints are always "
        "public; paid endpoints are gated behind on-chain x402 payments."
    ),
    contact={
        "name": "Rug Munch Media LLC",
        "url": "https://pryscraper.com",
        "email": "admin@rugmunch.io",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    terms_of_service="https://pryscraper.com/terms",
    openapi_tags=[
        {
            "name": "Scraping",
            "description": "Core scraping, crawling and browser-automation endpoints. "
            "Scrape any URL with the 10-tier anti-bot fallback chain, capture network "
            "patterns, and run adaptive relevance-based crawls.",
        },
        {
            "name": "Extraction",
            "description": "Structured data extraction: HTML tables, links, SEO analysis, "
            "Schema.org/JSON-LD, emails, CSS-selector extraction and LLM-powered extraction "
            "with intelligent chunking.",
        },
        {
            "name": "Commerce",
            "description": "Commerce, marketplace, costing, billing and subscription "
            "endpoints for the hosted Pry platform.",
        },
        {
            "name": "Auth",
            "description": "Authentication and API-key management. Protected endpoints "
            "require an `Authorization: Bearer <key>` header (or an rmi JWT).",
        },
        {
            "name": "Health",
            "description": "Liveness and readiness probes for the Pry service.",
        },
        {
            "name": "MCP",
            "description": "Model Context Protocol server (mounted at `/mcp`) exposing "
            "Pry's scraping, crawling, extraction and domain tools to AI agents over "
            "streaming SSE.",
        },
        {
            "name": "x402",
            "description": "x402 micropayment endpoints: pricing, payment requests, "
            "on-chain verification and settlement for pay-per-scrape operations.",
        },
        {
            "name": "Monitoring",
            "description": "Observability, alerting and integration-monitoring endpoints.",
        },
    ],
    servers=[
        {"url": "http://localhost:8002", "description": "Local development server"},
        {"url": "https://api.pryscraper.com", "description": "Production API"},
    ],
    lifespan=lifespan,
)

# MCP agent surface. PRY_MCP_ENABLED=false leaves /mcp unmounted entirely, so
# a self-host that does not want the agent surface has no route to attack (it
# is not "mounted but unauthorized"). The import is deliberately lazy so a
# switched-off instance never imports the MCP tool registry.
if MCP_ENABLED:
    from pry.api.mcp_server import mcp_app

    app.mount("/mcp", mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pryscraper.com",
        "https://api.pryscraper.com",
        "https://rugmunch.io",
        # Dev + internal app origins are covered by the regex below — do not
        # enumerate internal hostnames in public source (TOP-100 #11).
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    # Locked to first-party hosts only. No "*" wildcard. Subdomains of the
    # product (pryscraper.com) and the fleet dashboard (rugmunch.io).
    allow_origin_regex=r"https://(?:[a-z0-9-]+\.)*(?:pryscraper\.com|rugmunch\.io)",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth + rate limiting + timing middleware (see middleware.py).
app.add_middleware(PryHttpMiddleware)

# Classification lives in x402_middleware (DEFAULT_FREE_PATHS / PAID_ENDPOINTS)
# and is audited at startup by the lifespan hook — fail-closed.
# ORDER MATTERS: X402Middleware is added AFTER PryHttpMiddleware so it sits
# OUTERMOST — a keyless agent must reach the 402 challenge BEFORE the
# API-key auth layer rejects with 401. Verified payments mark
# scope["x402_verified"], which request_authorized accepts as the credential.
#
# PRY_X402_ENABLED=false omits the middleware entirely: the paid endpoints are
# then reachable like any other route, so a self-hoster's own instance serves
# its own keyless traffic for free (product policy 2026-09-26 — we do not gate
# first-party/self-hosted traffic against ourselves) and no facilitator,
# payee wallet or payment ledger is involved. The hosted/priced deployment
# leaves the switch on (default).
if X402_ENABLED:
    app.add_middleware(X402Middleware)

add_error_handlers(app)

# ── Routers ──
register_routers(app)


# ── x402 V2 spec endpoints ──
# GET /supported — payment kinds this server accepts (x402 V2 discovery).
# GET /readyz    — readiness probe (503 until the x402 facilitator is usable).
# (GET /healthz liveness already lives in pry.api.routers.core.health.)


@app.get(
    "/supported",
    tags=["x402"],
    summary="Supported x402 payment kinds",
    description="x402 V2 discovery: the payment schemes and networks this "
    "server accepts. Clients use this to build a valid PaymentRequired flow.",
)
async def supported_payment_kinds() -> dict[str, Any]:
    return {
        "kinds": [
            {"scheme": "exact", "network": "eip155:8453"},
            {"scheme": "exact", "network": "solana:mainnet"},
            {"scheme": "exact", "network": "tron:mainnet"},
        ]
    }


@app.get(
    "/readyz",
    tags=["Health"],
    summary="Readiness probe",
    description="Returns 200 when the x402 facilitator is configured and able "
    "to verify/settle payments; 503 otherwise. Load balancers should gate "
    "traffic on this endpoint.",
)
async def readyz() -> JSONResponse:
    from pry.payments.x402 import get_facilitator_router

    ready = bool(get_facilitator_router().readiness().get("ready"))
    if not ready:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "kinds": 3},
        )
    return JSONResponse(content={"status": "ready", "kinds": 3})


@app.get("/metrics", tags=["Ops"], include_in_schema=False)
async def get_metrics() -> str:
    """Prometheus text format metrics (real registry + x402 fallbacks)."""
    try:
        from prometheus_client import generate_latest

        return generate_latest().decode("utf-8")
    except Exception:  # noqa: BLE001 — fall back to static stubs
        lines = [
            "# TYPE x402_verify_total counter",
            "x402_verify_total 0",
            "# TYPE x402_settle_total counter",
            "x402_settle_total 0",
            "# TYPE x402_verify_failures_total counter",
            "x402_verify_failures_total 0",
            "# TYPE x402_facilitator_healthy gauge",
            "x402_facilitator_healthy 1",
        ]
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
