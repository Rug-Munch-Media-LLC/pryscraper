"""Pry v3 — Full-stack web intelligence API.
Scrape + Crawl + Automate + Parse + Extract + MCP
Self-hosted, free, better than Firecrawl."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any, cast

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from client import close_client
from deps import advanced, automator, extractor, queue, ratelimiter, scraper
from errors import (
    PryError,
)
from mcp_sse import mcp_post_message, mcp_sse_endpoint
from observability import REQUEST_COUNT, REQUEST_LATENCY, setup_tracing
from pipeline import get_pipeline
from pry_mcp import make_fallback_server, register_all
from routers.advanced import router as advanced_router
from routers.agency import router as agency_router
from routers.ai import router as ai_router
from routers.alerts import router as alerts_router
from routers.analysis import router as analysis_router
from routers.auth import router as auth_router
from routers.automation import router as automation_router
from routers.batch import router as batch_router
from routers.circuit_breaker import router as circuit_breaker_router
from routers.commerce import router as commerce_router
from routers.compliance import router as compliance_router
from routers.config import router as config_router
from routers.costing import router as costing_router
from routers.crm import router as crm_router
from routers.dashboard import router as dashboard_router
from routers.email import router as email_router
from routers.enrichment import router as enrichment_router
from routers.execute import router as execute_router
from routers.export import router as export_router
from routers.extraction import router as extraction_router
from routers.freshness import router as freshness_router
from routers.gdpr import router as gdpr_router
from routers.health import router as health_router
from routers.integrations import router as integrations_router
from routers.intelligence import router as intelligence_router
from routers.jobs import router as jobs_router
from routers.marketplace import router as marketplace_router
from routers.monitoring import router as monitoring_router
from routers.parsing import router as parsing_router
from routers.pipeline import router as pipeline_router
from routers.pipelines import router as pipelines_router
from routers.proxy import router as proxy_router
from routers.quality import router as quality_router
from routers.reconciliation import router as reconciliation_router
from routers.recorder import router as recorder_router
from routers.referrals import router as referrals_router
from routers.reports import router as reports_router
from routers.review import router as review_router
from routers.scraping import router as scraping_router
from routers.scraping_api import router as scraping_api_router
from routers.seo import router as seo_router
from routers.sessions import router as sessions_router
from routers.share import router as share_router
from routers.stats import router as stats_router
from routers.structure import router as structure_router
from routers.system import router as system_router
from routers.templates import router as templates_router
from routers.training import router as training_router
from routers.transform import router as transform_router
from routers.untagged import router as untagged_router
from routers.vision import router as vision_router
from routers.webhooks import router as webhooks_router
from routers.x402 import router as x402_router
from settings import settings
from x402_middleware import X402Middleware
from jwt_auth import validate_rmi_jwt, is_jwt

# Configure structured (JSON) logging for the whole process. Per
# CONVENTIONS.md Part 5, all Pry logs must be JSON with timestamp, level,
# service, and event. setup_logging() bridges stdlib logging through
# structlog so that any logger.info("event", k=v) becomes a JSON record.
try:
    from logging_config import get_logger as _get_logger
    from logging_config import setup_logging

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
    if not settings.api_key:
        logger.warning(
            "pry_api_key_unset",
            message="PRY_API_KEY is not set; all protected endpoints are publicly accessible",
        )
    get_pipeline()  # Initialize pipeline
    yield
    logger.info("pry_shutdown")
    await close_client()
    for obj in [scraper, automator, extractor, advanced, queue]:
        if hasattr(obj, "close"):
            with suppress(Exception):
                await obj.close()


app = FastAPI(
    title="Pry",
    version="3.0.0",
    description="Pry open any website. Web scraping + browser automation + document parsing. Self-hosted, free, better than Firecrawl.",
    lifespan=lifespan,
)

# ── MCP sub-app ──
# Mounted on /mcp so that streaming SSE endpoints bypass the main app's
# BaseHTTPMiddleware (which buffers response bodies and breaks SSE).
mcp_app = FastAPI(
    title="Pry MCP",
    version="3.0.0",
    description="Model Context Protocol endpoints for Pry.",
)
mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rugmunch.io",
        "https://[INTERNAL]",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_mcp_server_instance: Any | None = None


def _get_mcp_server() -> Any:
    """Lazy-initialize the spec-compliant MCP server."""
    global _mcp_server_instance
    if _mcp_server_instance is None:
        _mcp_server_instance = make_fallback_server(base_url=f"http://localhost:{settings.port}")
        register_all(_mcp_server_instance)
    return _mcp_server_instance


@mcp_app.post("/", tags=["MCP"], summary="MCP JSON-RPC endpoint")
async def mcp_json_rpc(request: Request) -> dict[str, Any]:
    """MCP JSON-RPC endpoint conforming to the 2024-11-05 spec."""
    body = await request.json()
    server = _get_mcp_server()
    return cast(dict[str, Any], await server.handle_request(body))


@mcp_app.get("/health", tags=["MCP"], summary="MCP server health")
async def mcp_health() -> dict[str, Any]:
    """Health check for the MCP server."""
    server = _get_mcp_server()
    return {
        "status": "ok",
        "server": "pry-mcp",
        "version": "3.0.0",
        "protocol_version": "2024-11-05",
        "tools_count": len(server.tools),
        "resources_count": len(server.resources),
        "prompts_count": len(server.prompts),
    }


@mcp_app.get("/sse", tags=["MCP"], summary="MCP HTTP+SSE transport")
async def mcp_sse(request: Request) -> StreamingResponse:
    """MCP HTTP+SSE transport endpoint."""
    return await mcp_sse_endpoint(request, _get_mcp_server())


@mcp_app.post("/messages/{session_id}", tags=["MCP"], summary="Post MCP JSON-RPC message")
async def mcp_messages(session_id: str, request: Request) -> Response:
    """Receive a JSON-RPC message for an active MCP SSE session."""
    return await mcp_post_message(request, session_id, _get_mcp_server())


app.mount("/mcp", mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rugmunch.io",
        "https://[INTERNAL]",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gate paid endpoints behind x402 payments. Free endpoints are always public.
app.add_middleware(
    X402Middleware,
    free_paths=[
        "/health",
        "/live",
        "/ready",
        "/docs",
        "/openapi.json",
        "/dashboard",
        "/v1/config",
        "/v1/ai/mcp-config",
        "/v1/x402/pricing",
        "/v1/x402/payment",
        "/v1/x402/verify",
        "/v1/x402/require-payment",
        "/v1/x402/pay",
        "/v1/x402/batch-payment",
        "/v1/x402/batch-verify",
        "/mcp",
        "/mcp/health",
        "/mcp/sse",
        "/mcp/messages/*",
    ],
)


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.to_dict(),
                "request_id": req_id,
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        logger.exception("unhandled_exception", extra={"request_id": req_id})
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {"code": "internal_error", "message": "An unexpected error occurred"},
                "request_id": req_id,
            },
        )


add_error_handlers(app)

# Public paths that don't need authentication
_AUTH_PUBLIC_PATHS: set[str] = {"/health", "/live", "/ready", "/docs", "/openapi.json"}


# Middleware: auth + rate limit + timing + request logging
class PryHttpMiddleware:
    """Pure-ASGI middleware for auth, rate limiting, timing, and logging.

    Implemented as ASGI (instead of @app.middleware('http')) so streaming
    responses such as Server-Sent Events are not buffered/broken by
    BaseHTTPMiddleware.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    @staticmethod
    def _get_header(scope: dict[str, Any], name: bytes) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == name.lower():
                return cast(bytes, value).decode("latin-1")
        return ""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.time()
        request_id = self._get_header(scope, b"x-request-id") or uuid.uuid4().hex[:12]
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        response_status = 200

        # Authentication check — supports PRY_API_KEY (legacy) and JWT from rmi-backend
        api_key = settings.api_key
        if api_key and path not in _AUTH_PUBLIC_PATHS:
            auth = self._get_header(scope, b"authorization")
            if auth.startswith("Bearer ") and auth[7:] == api_key:
                pass  # Legacy API key — allowed
            elif auth.startswith("Bearer "):
                token = auth[7:]
                if is_jwt(token) and validate_rmi_jwt(token):
                    pass  # JWT from rmi-backend — allowed
                else:
                    body = json.dumps(
                        {
                            "success": False,
                            "error": {"code": "unauthorized", "message": "Invalid or missing API key"},
                        }
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 401,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"x-request-id", request_id.encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return

        allowed, stats = ratelimiter.check(ip)
        if not allowed:
            elapsed = time.time() - start
            logger.warning(
                "rate_limit_blocked",
                extra={
                    "request_id": request_id,
                    "ip": ip,
                    "path": path,
                    "retry_after": stats.get("retry_after", 1),
                },
            )
            body = json.dumps(
                {
                    "success": False,
                    "error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
                    "retry_after": stats.get("retry_after", 1),
                }
            ).encode()
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-ratelimit-limit", str(ratelimiter.default_rpm).encode()),
                (b"x-ratelimit-remaining", b"0"),
                (b"x-ratelimit-reset", str(stats.get("retry_after", 1)).encode()),
                (b"x-request-id", request_id.encode()),
            ]
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        logger.info(
            "request_start",
            extra={
                "request_id": request_id,
                "method": scope.get("method", "GET"),
                "path": path,
                "ip": ip,
            },
        )

        ratelimit_limit = str(ratelimiter.default_rpm).encode()
        ratelimit_remaining = str(stats.get("remaining", 0)).encode()
        ratelimit_reset = str(stats.get("reset_at", 0)).encode()
        request_id_bytes = request_id.encode()

        async def wrapped_send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", ratelimit_limit))
                headers.append((b"x-ratelimit-remaining", ratelimit_remaining))
                headers.append((b"x-ratelimit-reset", ratelimit_reset))
                headers.append((b"x-request-id", request_id_bytes))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)

        elapsed = time.time() - start
        if REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(method=method, endpoint=path, status=str(response_status)).inc()
            REQUEST_LATENCY.labels(endpoint=path).observe(elapsed)
        logger.info(
            "request_end",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": response_status,
                "duration": f"{elapsed:.3f}s",
            },
        )


app.add_middleware(PryHttpMiddleware)


# ── Stats ──


# ── Costing ──


# ── Freshness ──


# ── Parse (Documents) ──


# ── Automate (Browser) ──


# ── Vision — analyze an image via free OpenRouter vision models ───────────────
# Free models default to google/gemma-4-31b-it:free. Accepts:
#   - image (base64 data URI or raw base64)
#   - url (auto-screenshots, then analyzes)
#   - file_path (local PNG/JPG)
#   - question (what to ask about the image)
#   - model (override default)
#   - max_tokens (default 800)
#
# Auto-fallback: if primary model 429s, tries other free models in order.


# ── Sessions ──────────────────────────────────────────────────────────────────


# ── Email Inbox Scraping ──


# ── Integrations ──


# ── Alerts ──


# ── Jobs ──


# ── Config ──


# ── Win 3: WebSocket streaming ──


# ── Win 5: Batch from file + template ──


# ── Win 6: Browser recorder ──


# ── Win 8: Multi-format transform ──


# ── Win 1: Pryfile execution ──


# ── Win 10: Health dashboard HTML ──


# ── Win 1: AI Schema Suggestion ──


# ── Win 2: Circuit Breaker ──


# ── Win 3: Stable Extraction ──


# ── Pipeline hooks ──


# ── Win 4: Data Pipeline ──


# ── Win 5: Shareable Results ──


# ── Compliance ──


# ── GDPR Compliance Portal ──


# ── AI Training Data Pipeline ──


# ── Monitoring (cron-based content change detection with AI judging) ──


# ── Structure Monitor ──


# ── Intelligence (Competitive Intelligence Engine) ──


# ── Quality ──


# ── Reconciliation ──


# ── Auth ──
# (split into routers/auth.py on the api-router-split refactor)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(scraping_router)
app.include_router(templates_router)
app.include_router(ai_router)
app.include_router(advanced_router)
app.include_router(agency_router)
app.include_router(alerts_router)
app.include_router(analysis_router)
app.include_router(automation_router)
app.include_router(batch_router)
app.include_router(crm_router)
app.include_router(circuit_breaker_router)
app.include_router(commerce_router)
app.include_router(compliance_router)
app.include_router(config_router)
app.include_router(costing_router)
app.include_router(dashboard_router)
app.include_router(email_router)
app.include_router(enrichment_router)
app.include_router(execute_router)
app.include_router(export_router)
app.include_router(extraction_router)
app.include_router(freshness_router)
app.include_router(gdpr_router)
app.include_router(integrations_router)
app.include_router(intelligence_router)
app.include_router(jobs_router)
app.include_router(marketplace_router)
app.include_router(monitoring_router)
app.include_router(parsing_router)
app.include_router(pipeline_router)
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
app.include_router(stats_router)
app.include_router(structure_router)
app.include_router(system_router)
app.include_router(training_router)
app.include_router(transform_router)
app.include_router(untagged_router)
app.include_router(vision_router)
app.include_router(webhooks_router)
app.include_router(x402_router)


# ── Review ──


# ── Commerce Sync ──


# ── CRM Sync ──


# ── Pipeline Builder Endpoints ──


# ── Agency ──


# ── SEO Content Change Monitor ──


# ── Reports ──


# ── Enrichment ──


# ── AI Agent Integration ──


# ── Proxy Provider & Affiliate Signup Flow ──


# ── Advanced Scraping (TLS, GraphQL, Schema.org, WebSocket) ──


# ── Advanced: Cookie Warming, PDF, OCR, Dedup, Behavior ──


# ── x402 payment processing ──


# ── Actor marketplace ──


# ── Webhook delivery ──


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
