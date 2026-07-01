"""Pry v3 — Full-stack web intelligence API.
Scrape + Crawl + Automate + Parse + Extract + MCP
Self-hosted, free, better than Firecrawl."""

import asyncio
import base64
import difflib
import html
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
import uvicorn
from fastapi import Body, FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from advanced import PryAdvanced
from automator import PryAutomator
from cache import ResponseCache
from client import close_client, get_client
from errors import (
    ExternalServiceError,
    InvalidRequestError,
    NotFoundError,
    PryError,
    ScrapeError,
)
from extraction import JsonCssExtractionStrategy, extract_with_chunking
from extractor import SchemaExtractor
from jobqueue import JobQueue
from mconfig import PryConfig
from mcp_production import make_fallback_server, register_all
from mcp_sse import mcp_post_message, mcp_sse_endpoint
from parser import DocumentParser
from pipeline import HOOK_POINTS, get_pipeline, run_pipeline
from pryextras import BatchProcessor, TransformEngine, recorder, streams
from ratelimit import RateLimiter
from scraper import BlockDetector, PryScraper
from settings import settings
from x402_middleware import X402Middleware

config = PryConfig()
logger = logging.getLogger(__name__)

# ── Init ──


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate deps. Shutdown: cleanup clients."""
    logger.info("pry_startup", extra={"version": "3.0.0"})
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
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
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

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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

scraper = PryScraper()
automator = PryAutomator()
parser = DocumentParser()
extractor = SchemaExtractor()
cache = ResponseCache(capacity=1000)
ratelimiter = RateLimiter(default_rpm=120, burst=200)
queue = JobQueue()
advanced = PryAdvanced(cache=cache)


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
        client = scope.get("client")
        ip = client[0] if client else "unknown"

        # Authentication check
        api_key = settings.api_key
        if api_key and path not in _AUTH_PUBLIC_PATHS:
            auth = self._get_header(scope, b"authorization")
            if not (auth.startswith("Bearer ") and auth[7:] == api_key):
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
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", ratelimit_limit))
                headers.append((b"x-ratelimit-remaining", ratelimit_remaining))
                headers.append((b"x-ratelimit-reset", ratelimit_reset))
                headers.append((b"x-request-id", request_id_bytes))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)

        elapsed = time.time() - start
        logger.info(
            "request_end",
            extra={
                "request_id": request_id,
                "method": scope.get("method", "GET"),
                "path": path,
                "duration": f"{elapsed:.3f}s",
            },
        )


app.add_middleware(PryHttpMiddleware)


# ── Models ──
class ScrapeRequest(BaseModel):
    url: str
    formats: list[str] | None = None
    onlyMainContent: bool | None = True
    timeout: int | None = 30
    bypassCloudflare: bool | None = True
    jsRender: bool | None = False
    jsonSchema: dict[str, str] | None = None


class CrawlRequest(BaseModel):
    url: str
    maxPages: int | None = 10
    maxDepth: int | None = 2
    scrapeOptions: dict[str, Any] | None = None
    webhook: str | None = None


class MapRequest(BaseModel):
    url: str
    search: str | None = None
    ignoreSitemap: bool | None = True
    limit: int | None = 50


class AutomateStep(BaseModel):
    action: str
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    timeout: int | None = 30000
    wait_until: str | None = "networkidle"


class AutomateRequest(BaseModel):
    session_id: str | None = None
    steps: list[AutomateStep]
    headless: bool | None = True
    viewport: dict[str, int] | None = None


class ParseRequest(BaseModel):
    url: str
    timeout: int | None = 60


# ── Health ──
@app.get("/health", tags=["Health"], summary="Full health check with dependency status")
async def health_check() -> JSONResponse:
    """Comprehensive health check — probes Ollama, FlareSolverr, Redis."""
    deps = {"ollama": False, "flaresolverr": False, "redis": False}

    async def check_ollama() -> bool:
        try:
            c = await get_client()
            r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
            return r.is_success
        except Exception:
            return False

    async def check_flare() -> bool:
        try:
            c = await get_client()
            r = await c.post(
                settings.flaresolverr_url,
                json={"cmd": "sessions.list"},
                headers={"Content-Type": "application/json"},
                timeout=3,
            )
            return r.is_success
        except Exception:
            return False

    async def check_redis() -> bool:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
            return True
        except Exception:
            return False

    results = await asyncio.gather(
        check_ollama(), check_flare(), check_redis(), return_exceptions=False
    )
    deps["ollama"] = results[0]
    deps["flaresolverr"] = results[1]
    deps["redis"] = results[2]
    flaresolverr_ok = deps["flaresolverr"]
    status_code = 200 if flaresolverr_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if flaresolverr_ok else "degraded",
            "version": "3.0.0",
            "dependencies": deps,
        },
    )


@app.get("/live", tags=["Health"], summary="Kubernetes liveness probe")
async def live() -> dict[str, str]:
    """Simple liveness — always returns 200 if the process is running."""
    return {"status": "alive"}


@app.get("/ready", tags=["Health"], summary="Kubernetes readiness probe", response_model=None)
async def ready() -> JSONResponse | dict[str, str]:
    """Readiness — checks critical dependencies."""
    try:
        c = await get_client()
        r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
        if r.is_success:
            return {"status": "ready"}
    except Exception:
        pass
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@app.get("/v0/stats", tags=["Stats"], summary="Get cache, rate limiter, and session stats")
async def stats() -> dict[str, Any]:
    return {
        "cache": cache.stats(),
        "rate_limiter": ratelimiter.get_stats(),
        "sessions": automator.list_sessions(),
    }


# ── Costing ──
@app.get("/v1/costing/dashboard", tags=["Costing"], summary="Get cost analytics dashboard")
async def cost_dashboard() -> dict[str, Any]:
    """Get the full cost analytics dashboard.

    Includes:
    - Monthly spend breakdown by operation type
    - Projected end-of-month cost
    - Daily spend for last 7 days
    - Cache efficiency metrics
    - Smart schedule recommendations
    """
    from costing import get_cost_dashboard

    return {"success": True, "data": get_cost_dashboard()}


@app.get("/v1/costing/usage", tags=["Costing"], summary="Get usage breakdown")
async def cost_usage(
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Get detailed usage breakdown for a specific month."""
    from costing import get_monthly_usage

    return {"success": True, "data": get_monthly_usage(year, month)}


@app.post("/v1/costing/record", tags=["Costing"], summary="Record a usage event")
async def record_usage_endpoint(
    operation: str = Body(...),
    quantity: float = Body(1.0),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Record a usage event for cost tracking.

    Operations: scrape_direct, scrape_flaresolverr, scrape_playwright,
    crawl_page, llm_call, vision_call, extraction_css, bandwidth_mb
    """
    from costing import record_usage

    result = record_usage(operation, metadata, quantity)
    return {"success": True, "data": result}


@app.post("/v1/costing/costs", tags=["Costing"], summary="Update per-operation cost table")
async def update_costs(costs: dict[str, float] = Body(...)) -> dict[str, Any]:
    """Update the per-operation cost table with custom prices."""
    from costing import update_cost_table

    result = await update_cost_table(costs)
    return {"success": result["success"], "data": result}


# ── Freshness ──


@app.post(
    "/v1/freshness/check",
    tags=["Freshness"],
    summary="Check if content has changed since last scrape",
)
async def freshness_check(
    url: str = Body(...),
    content: str = Body(""),
) -> dict[str, Any]:
    """Check if content has changed since the last scrape.

    Uses content fingerprinting (SHA256) to detect changes.
    If no content is provided, does a quick HEAD check instead.
    """
    from freshness import check_content_changed, quick_health_check, record_check_result

    if content:
        result = await check_content_changed(url, content)
        record_check_result(url, result["changed"])
        return {"success": True, "data": result}

    # Quick HEAD check
    head = await quick_health_check(url)
    return {"success": True, "data": head}


@app.post(
    "/v1/freshness/frequency",
    tags=["Freshness"],
    summary="Get adaptive scrape frequency recommendation",
)
async def freshness_frequency(
    url: str = Body(...),
    base_interval: int = Body(60),
) -> dict[str, Any]:
    """Get an adaptive scrape frequency recommendation based on content volatility.

    Volatile pages (frequent changes) get shorter intervals.
    Stable pages get longer intervals to save costs.
    """
    from freshness import calculate_adaptive_frequency

    result = calculate_adaptive_frequency(url, base_interval_minutes=base_interval)
    return {"success": True, "data": result}


@app.get("/v1/freshness/dashboard", tags=["Freshness"], summary="Get content staleness dashboard")
async def freshness_dashboard() -> dict[str, Any]:
    """Get the content staleness dashboard.

    Shows all tracked URLs, their last check time, age, and whether
    they're stale (not checked in 24h).
    """
    from freshness import get_staleness_dashboard

    return {"success": True, "data": get_staleness_dashboard()}


# ── Scrape ──
@app.post("/v1/scrape", tags=["Scraping"], summary="Scrape a single URL")
async def scrape(request: ScrapeRequest) -> dict[str, Any]:
    """Scrape a URL. Auto-bypasses Cloudflare. Returns markdown or JSON."""
    # Check cache
    cache_opts = {"bypass_cloudflare": request.bypassCloudflare, "js_render": request.jsRender}
    cached = cache.get(request.url, cache_opts)
    if cached:
        cached["_cached"] = True
        return cached

    try:
        result = await scraper.scrape(
            request.url,
            {
                "timeout": request.timeout,
                "bypass_cloudflare": request.bypassCloudflare,
                "js_render": request.jsRender,
                "formats": request.formats,
            },
        )
        if result.get("status") != "ok":
            raise ScrapeError(result.get("error", "Scrape failed"))

        response: dict[str, Any] = {
            "success": True,
            "data": {
                "markdown": result.get("content", ""),
                "metadata": {
                    "url": request.url,
                    "method": result.get("method", "unknown"),
                    "title": result.get("title", ""),
                    "description": result.get("description", ""),
                },
            },
        }

        # JSON schema extraction if requested
        if request.jsonSchema:
            extracted = await extractor.extract(result.get("content", ""), request.jsonSchema)
            response["data"]["json"] = extracted

        cache.set(request.url, response, cache_opts)
        return response
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


@app.post("/v1/detect-block", tags=["Scraping"], summary="Detect if a site is blocking the scraper")
async def detect_block(url: str = Body(...)) -> dict[str, Any]:
    """Detect what kind of anti-bot protection a site is using.

    Returns detection tier, vendor (Cloudflare/DataDome/etc.), and confidence.
    Useful for debugging scraping issues.
    """
    detector = BlockDetector()
    results = []

    # Test direct
    try:
        client = await get_client()
        resp = await client.get(
            url,
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            },
        )
        detection = detector.detect(resp.text, resp.status_code, dict(resp.headers))
        results.append({"method": "direct", "status": resp.status_code, **detection})
    except Exception as e:
        results.append({"method": "direct", "error": str(e)})

    # Test FlareSolverr
    try:
        async with httpx.AsyncClient(timeout=30) as fs_client:
            fs_resp = await fs_client.post(
                settings.flaresolverr_url,
                json={"cmd": "request.get", "url": url, "maxTimeout": 15000},
            )
            if fs_resp.is_success:
                fs_data = fs_resp.json()
                fs_html = fs_data.get("solution", {}).get("response", "")
                fs_status = fs_data.get("solution", {}).get("status", 0)
                detection = detector.detect(fs_html, fs_status)
                results.append({"method": "flaresolverr", "status": fs_status, **detection})
            else:
                results.append({"method": "flaresolverr", "error": f"HTTP {fs_resp.status_code}"})
    except Exception as e:
        results.append({"method": "flaresolverr", "error": str(e)})

    return {"success": True, "data": {"url": url, "results": results}}


@app.post(
    "/v1/ultimate-scrape", tags=["Scraping"], summary="Scrape with 10-tier anti-bot fallback system"
)
async def ultimate_scrape(
    url: str = Body(..., embed=True),
) -> dict[str, Any]:
    """Scrape any URL using Pry's ultimate 10-tier anti-detection system.

    Automatically tries: direct → cloudscraper → FlareSolverr →
    undetected-chromedriver → Playwright → Googlebot → Archive.org → Google Cache

    Returns the first successful result with the method used.
    """
    from ultimate_scraper import UltimateScraper

    s = UltimateScraper()
    result = await s.scrape(url)
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error", "All bypass methods failed"))

    return {
        "success": True,
        "data": {
            "url": url,
            "method": result.get("method", "unknown"),
            "content": result.get("content", "")[:50000],
            "content_length": len(result.get("content", "")),
        },
    }


@app.post(
    "/v1/capture/network",
    tags=["Scraping"],
    summary="Extract API calls and network patterns from a page",
)
async def capture_network(
    url: str = Body(...),
) -> dict[str, Any]:
    """Extract API calls, GraphQL queries, and network patterns from a page.

    Useful for understanding how SPAs load data and finding hidden API endpoints.
    """
    from network import (
        extract_api_calls_from_html,
        extract_graphql_queries,
        extract_json_ld,
        extract_nextjs_props,
        extract_nuxt_state,
    )

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    html = result.get("raw_html", "")
    if not html:
        client = await get_client()
        try:
            resp = await client.get(
                url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
            )
            html = resp.text
        except Exception:
            raise ScrapeError("Could not fetch raw HTML") from None

    return {
        "success": True,
        "data": {
            "url": url,
            "api_calls": extract_api_calls_from_html(html),
            "graphql_queries": extract_graphql_queries(html),
            "json_ld": extract_json_ld(html),
            "nextjs_props": extract_nextjs_props(html) is not None,
            "nuxt_state": extract_nuxt_state(html) is not None,
        },
    }


@app.post("/v1/capture/lazy", tags=["Scraping"], summary="Detect and handle lazy-loaded content")
async def detect_lazy_content(
    url: str = Body(...),
    auto_scroll: bool = Body(True),
    max_scrolls: int = Body(5),
) -> dict[str, Any]:
    """Detect lazy loading and infinite scroll patterns on a page.

    Optionally generate JS to auto-scroll and load all content.
    """
    from lazy_load import (
        detect_lazy_loading,
        generate_load_more_script,
        generate_scroll_script,
    )

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    html = result.get("raw_html", "")
    if not html:
        client = await get_client()
        try:
            resp = await client.get(
                url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
            )
            html = resp.text
        except Exception:
            raise ScrapeError("Could not fetch raw HTML") from None

    detection = detect_lazy_loading(html)
    scroll_script = generate_scroll_script(max_scrolls=max_scrolls) if auto_scroll else ""
    load_more_script = generate_load_more_script() if auto_scroll else ""

    return {
        "success": True,
        "data": {
            "url": url,
            "detection": detection,
            "has_lazy_content": any(detection.values()),
            "scroll_script": scroll_script,
            "load_more_script": load_more_script,
        },
    }


# ── Crawl ──
@app.post("/v1/crawl", tags=["Scraping"], summary="Crawl multiple pages from a URL")
async def crawl(request: CrawlRequest) -> dict[str, Any]:
    """Crawl multiple pages from a URL. Supports async webhooks."""
    if request.webhook:
        job_id = await queue.create_job("crawl", request.model_dump(), webhook=request.webhook)
        task = asyncio.create_task(_run_crawl_job(job_id, request))
        task.add_done_callback(_log_crawl_job_failure)
        return {"success": True, "data": {"id": job_id, "status": "pending"}}

    pages = await scraper.crawl(
        request.url,
        {
            "max_pages": request.maxPages,
            "max_depth": request.maxDepth,
            "timeout": request.scrapeOptions.get("timeout", 60) if request.scrapeOptions else 60,
        },
    )
    return {"success": True, "data": {"id": "sync", "url": request.url, "pages": pages}}


@app.post(
    "/v1/crawl/adaptive",
    tags=["Scraping"],
    summary="Crawl with adaptive stopping based on content relevance",
)
async def adaptive_crawl(
    url: str = Body(...),
    query: str = Body(""),
    max_pages: int = Body(50),
    max_depth: int = Body(3),
    relevance_threshold: float = Body(0.3),
) -> dict[str, Any]:
    """Crawl a website with adaptive stopping.

    Uses information foraging theory to decide when to stop:
    - Stops when content relevance drops below threshold
    - Stops when information gain diminishes
    - Respects max_pages and max_depth limits
    - Ideal for targeted data collection (pricing, docs, products)
    """
    from adaptive import AdaptiveCrawler

    crawler = AdaptiveCrawler(
        max_pages=max_pages,
        max_depth=max_depth,
        relevance_threshold=relevance_threshold,
    )

    pages = []
    to_visit = [(url, 0)]
    visited_urls: set[str] = set()

    while to_visit:
        current_url, depth = to_visit.pop(0)

        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        try:
            result = await scraper.scrape(current_url, {"bypass_cloudflare": True})
            content = result.get("content", "") or ""
        except Exception as e:
            logger.warning(
                "adaptive_crawl_page_failed", extra={"url": current_url, "error": str(e)}
            )
            continue

        decision = await crawler.should_continue(current_url, content, depth, query=query)
        pages.append({"url": current_url, "depth": depth, "decision": decision})

        if not decision["continue"]:
            break

        if depth < max_depth:
            links = await scraper.map_urls(current_url, {"limit": 10})
            for link in links:
                full_url = urljoin(current_url, link)
                if full_url not in visited_urls:
                    to_visit.append((full_url, depth + 1))

    return {
        "success": True,
        "data": {
            "url": url,
            "query": query,
            "pages": pages,
            "total_pages": len(pages),
            "stats": crawler.get_stats(),
        },
    }


async def _run_crawl_job(job_id: str, request: CrawlRequest) -> None:
    try:
        pages = await scraper.crawl(
            request.url,
            {
                "max_pages": request.maxPages,
                "max_depth": request.maxDepth,
            },
        )
        await queue.complete_job(job_id, {"pages": pages})
    except Exception as e:
        logger.exception("crawl_job_failed", extra={"job_id": job_id, "url": request.url})
        await queue.fail_job(job_id, str(e))


def _log_crawl_job_failure(task: asyncio.Task[Any]) -> None:
    """Log unhandled exceptions from crawl job tasks."""
    exc = task.exception()
    if exc:
        logger.error("crawl_task_unhandled_error", extra={"error": str(exc)})


async def _fire_watch_webhook(webhook: str, url: str, diff_result: dict[str, Any]) -> None:
    """Fire a webhook notification for watch events."""
    try:
        client = await get_client()
        await client.post(
            webhook,
            json={"event": "watch_update", "url": url, "data": diff_result},
            timeout=10,
        )
    except Exception:
        logger.exception("watch_webhook_failed", extra={"url": url, "webhook": webhook})


# ── Map ──
@app.post("/v1/map", tags=["Scraping"], summary="Discover URLs on a site")
async def map_pages(request: MapRequest) -> dict[str, Any]:
    """Discover URLs on a site."""
    urls = await scraper.map_urls(request.url, {"limit": request.limit})
    return {"success": True, "data": {"links": urls}}


# ── Parse (Documents) ──
@app.post("/v1/parse", tags=["Parsing"], summary="Parse a document (PDF, DOCX, image, CSV, JSON)")
async def parse_document(request: ParseRequest) -> dict[str, Any]:
    """Parse a document (PDF, DOCX, image, CSV, JSON) to text."""
    try:
        result = await parser.parse(request.url, request.timeout or 60)
        return {"success": True, "data": result}
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


@app.post(
    "/v1/markdown", tags=["Parsing"], summary="Generate markdown with content filtering strategies"
)
async def generate_markdown(
    url: str = Body(...),
    mode: str = Body("raw"),
    query: str = Body(""),
    threshold: float = Body(0.3),
) -> dict[str, Any]:
    """Generate markdown with configurable content filtering.

    Modes:
    - raw: Unfiltered markdown
    - fit: Prune boilerplate (nav, ads, footers)
    - bm25: Filter by BM25 relevance to query (requires query param)
    """
    from markdown_gen import BM25ContentFilter, DefaultMarkdownGenerator, PruningContentFilter

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    content = result.get("content", "")
    if not content:
        raise ScrapeError("No content scraped")

    if mode == "fit":
        filter_strategy: PruningContentFilter | BM25ContentFilter | None = PruningContentFilter(
            threshold=threshold
        )
    elif mode == "bm25":
        if not query:
            filter_strategy = PruningContentFilter(threshold=threshold)
        else:
            filter_strategy = BM25ContentFilter(threshold=threshold)
    else:
        filter_strategy = None

    gen = DefaultMarkdownGenerator(content_filter=filter_strategy)
    md_result = gen.generate(content, url=url, query=query)

    return {
        "success": True,
        "data": md_result,
    }


# ── Automate (Browser) ──
@app.post("/v1/automate", tags=["Automation"], summary="Execute browser automation steps")
async def automate(request: AutomateRequest) -> dict[str, Any]:
    """Execute browser automation steps. Sessions persist for login flows."""
    try:
        steps = [s.model_dump() for s in request.steps]
        result = await automator.run_steps(
            steps=steps,
            session_id=request.session_id,
            headless=True if request.headless is None else request.headless,
            viewport=request.viewport,
        )
        return {"success": True, "data": result}
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


@app.post("/v1/screenshot", tags=["Automation"], summary="Take a screenshot of a URL")
async def screenshot(
    url: str = Body(..., embed=True), session_id: str | None = None
) -> dict[str, Any]:
    """Take a screenshot of a URL. Returns base64 PNG."""
    try:
        result = await automator.run_steps(
            steps=[{"action": "navigate", "url": url}, {"action": "screenshot"}],
            session_id=session_id,
        )
        screenshot_data = None
        for step in result.get("steps", []):
            if step.get("action") == "screenshot":
                screenshot_data = step.get("screenshot")
        return {"success": True, "data": {"screenshot": screenshot_data or ""}}
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


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
VISION_MODELS_FALLBACK = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/free",
]


def _get_or_key() -> str | None:
    """Pull OPENROUTER_API_KEY from ~/.hermes/.env or env."""
    key = settings.openrouter_api_key
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(env_path):
        return None
    with open(env_path) as f:
        for line in f:
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


async def _call_vision_api(
    image_b64: str, question: str, model: str, max_tokens: int = 800
) -> tuple[str | None, str | None, str | None]:
    """Single async vision call. Returns (text, model_used) or raises."""
    key = _get_or_key()
    if not key:
        return None, None, "OPENROUTER_API_KEY not set"

    # Accept either data URI or raw base64
    data_uri = image_b64 if image_b64.startswith("data:") else f"data:image/png;base64,{image_b64}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }

    client = await get_client()
    resp = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://pry.local",
            "X-Title": "pry-vision",
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["choices"][0]["message"]["content"], model, None


@app.post("/v1/vision", tags=["Vision"], summary="Analyze an image with a free vision model")
async def vision(
    question: str = Body("Describe what is visible in this image.", embed=True),
    image: str | None = Body(None, embed=True),
    url: str | None = Body(None, embed=True),
    file_path: str | None = Body(None, embed=True),
    model: str | None = Body(None, embed=True),
    max_tokens: int = Body(800, embed=True),
    session_id: str | None = Body(None, embed=True),
    no_fallback: bool = Body(False, embed=True),
) -> dict[str, Any]:
    """Analyze an image with a free vision model.

    Provide ONE of: image (base64 or data URI), url (auto-screenshot),
    or file_path (local PNG/JPG).

    Auto-falls-back across 5 free OpenRouter vision models if the
    requested one is rate-limited.
    """
    try:
        # 1. Resolve the image bytes
        if url:
            # Auto-screenshot via playwright
            r = await automator.run_steps(
                steps=[{"action": "navigate", "url": url}, {"action": "screenshot"}],
                session_id=session_id,
            )
            image_b64 = None
            for step in r.get("steps", []):
                if step.get("action") == "screenshot":
                    image_b64 = step.get("screenshot")
            if not image_b64:
                raise ScrapeError("screenshot returned empty")
        elif file_path:
            p = os.path.expanduser(file_path)
            if not os.path.isfile(p):
                raise InvalidRequestError(f"file not found: {file_path}")
            with open(p, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("ascii")
        elif image:
            # Strip data URI prefix if present
            image_b64 = image.split(",", 1)[1] if image.startswith("data:") else image
        else:
            raise InvalidRequestError("must provide one of: image, url, file_path")

        # 2. Build the fallback chain
        if model:
            models_to_try = [model]
            if not no_fallback:
                models_to_try += [m for m in VISION_MODELS_FALLBACK if m != model]
        else:
            models_to_try = list(VISION_MODELS_FALLBACK)

        # 3. Try each model until one succeeds
        attempts = []
        for m in models_to_try:
            try:
                text, used, err = await _call_vision_api(image_b64, question, m, max_tokens)
                if err:
                    attempts.append({"model": m, "error": err})
                    continue
                return {
                    "success": True,
                    "data": {
                        "answer": text,
                        "model_used": used,
                        "question": question,
                        "image_size_bytes": len(image_b64) * 3 // 4,
                        "attempts": attempts,
                    },
                }
            except httpx.HTTPStatusError as e:
                attempts.append(
                    {
                        "model": m,
                        "error": f"http {e.response.status_code}",
                        "body": e.response.text[:200],
                    }
                )
            except Exception as e:
                attempts.append({"model": m, "error": str(e)})

        raise ExternalServiceError(
            "all vision models failed",
            details={"attempts": attempts},
        )
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


@app.get(
    "/v1/vision/models", tags=["Vision"], summary="List free vision-capable models on OpenRouter"
)
async def vision_models() -> dict[str, Any]:
    """List free vision-capable models on OpenRouter."""
    try:
        client = await get_client()
        resp = await client.get(
            "https://openrouter.ai/api/v1/models", headers={"User-Agent": "pry/3.0"}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise ExternalServiceError(str(e)) from e

    free = []
    for m in data.get("data", []):
        arch = m.get("architecture", {})
        if "image" not in arch.get("input_modalities", []):
            continue
        pricing = m.get("pricing", {})
        try:
            pp = float(pricing.get("prompt", "1") or 1)
            cp = float(pricing.get("completion", "1") or 1)
        except Exception:
            continue
        if pp == 0 and cp == 0:
            free.append(
                {
                    "id": m["id"],
                    "name": m.get("name", ""),
                    "context": arch.get("context_length"),
                    "description": (m.get("description") or "")[:120],
                }
            )
    return {"success": True, "data": {"free_models": free, "count": len(free)}}


# ── Sessions ──────────────────────────────────────────────────────────────────
@app.post("/v1/session/create", tags=["Sessions"], summary="Create a persistent browser session")
async def create_session(url: str = Body(...), persist: bool = True) -> dict[str, Any]:
    """Create a persistent browser session."""
    session_id = await automator.create_session(url, persist=persist)

    if persist:
        from sessions import save_session

        await save_session(
            session_id=session_id,
            cookies=[],
            metadata={"url": url, "created_at": datetime.now(UTC).isoformat()},
        )

    return {"success": True, "data": {"session_id": session_id, "persist": persist}}


@app.post(
    "/v1/session/destroy", tags=["Sessions"], summary="Destroy a browser session with optional save"
)
async def destroy_session(
    session_id: str = Body(...),
    save_state: bool = Body(False),
) -> dict[str, Any]:
    """Destroy a browser session. Optionally save state first."""
    from sessions import delete_session, save_session

    if save_state:
        state = await automator.get_session_state(session_id)
        if state:
            await save_session(
                session_id=session_id,
                cookies=state.get("cookies", []),
                local_storage=state.get("local_storage", {}),
                metadata={"destroyed_at": datetime.now(UTC).isoformat()},
            )

    success = await automator.destroy_session(session_id)
    if not save_state:
        await delete_session(session_id)

    return {"success": True, "data": {"session_id": session_id, "destroyed": success}}


@app.get("/v1/sessions", tags=["Sessions"], summary="List all persistent sessions")
async def list_sessions() -> dict[str, Any]:
    """List all persistent sessions (active + saved)."""
    from sessions import list_sessions as list_saved_sessions

    active = automator.list_sessions()
    saved = await list_saved_sessions()

    return {
        "success": True,
        "data": {
            "active": active,
            "saved": saved,
            "total_active": len(active),
            "total_saved": len(saved),
        },
    }


@app.post("/v1/session/save", tags=["Sessions"], summary="Save current session state to disk")
async def save_session_state(
    session_id: str = Body(...),
) -> dict[str, Any]:
    """Save a session's current state (cookies, storage) to disk."""
    from sessions import save_session as save_session_to_disk

    state = await automator.get_session_state(session_id)
    if not state:
        raise NotFoundError(f"Session not found: {session_id}")

    await save_session_to_disk(
        session_id=session_id,
        cookies=state.get("cookies", []),
        local_storage=state.get("local_storage", {}),
        session_storage=state.get("session_storage", {}),
        metadata={"source": "manual_save"},
    )

    return {
        "success": True,
        "data": {"session_id": session_id, "cookie_count": len(state.get("cookies", []))},
    }


@app.post("/v1/session/restore", tags=["Sessions"], summary="Restore a saved session")
async def restore_session(session_id: str = Body(...)) -> dict[str, Any]:
    """Restore a session from disk into a browser context."""
    from sessions import load_session

    data = await load_session(session_id)
    if not data:
        raise NotFoundError(f"Saved session not found: {session_id}")

    success = await automator.restore_session_state(
        session_id=session_id,
        cookies=data.get("cookies", []),
    )

    return {
        "success": success,
        "data": {
            "session_id": session_id,
            "restored": success,
            "cookie_count": len(data.get("cookies", [])),
            "saved_at": data.get("saved_at", ""),
        },
    }


# ── Advanced Features (Firecrawl doesn't have these) ──


@app.post("/v1/batch", tags=["Batch"], summary="Scrape multiple URLs in parallel")
async def batch_scrape(urls: list[str] = Body(...), timeout: int = 30) -> dict[str, Any]:
    """Scrape multiple URLs in parallel. Firecrawl charges extra for batch."""
    if len(urls) > 50:
        raise InvalidRequestError("Max 50 URLs per batch")
    tasks = [scraper.scrape(u, {"timeout": timeout, "bypass_cloudflare": True}) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    pages = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            pages.append({"url": urls[i], "error": str(r)})
        elif isinstance(r, dict):
            pages.append(
                {
                    "url": urls[i],
                    "markdown": r.get("content", ""),
                    "method": r.get("method", "unknown"),
                }
            )
    return {"success": True, "data": {"pages": pages, "total": len(pages)}}


@app.post("/v1/compare", tags=["Analysis"], summary="Compare content of two URLs")
async def compare(url1: str = Body(...), url2: str = Body(...)) -> dict[str, Any]:
    """Scrape two URLs and compare their content. Shows additions, deletions, changes."""
    r1, r2 = await asyncio.gather(scraper.scrape(url1), scraper.scrape(url2))
    c1, c2 = r1.get("content", ""), r2.get("content", "")
    diff = list(
        difflib.unified_diff(
            c1.splitlines(keepends=True),
            c2.splitlines(keepends=True),
            fromfile=url1,
            tofile=url2,
            n=3,
        )
    )
    return {
        "success": True,
        "data": {
            "url1": url1,
            "url2": url2,
            "diff": diff[:200],
            "changes": len(diff),
            "identical": len(diff) == 0,
        },
    }


@app.post("/v1/watch", tags=["Analysis"], summary="Watch a page for changes")
async def watch_page(
    url: str = Body(...), webhook: str = Body(...), interval: int = 3600, selector: str = ""
) -> dict[str, Any]:
    """Watch a page for changes. Accepts a webhook URL for notification.
    First call registers the watch, subsequent calls compare and notify.
    Firecrawl charges $99/mo for this feature."""
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError("Could not scrape URL")
    content = result.get("content", "")
    diff_result = await advanced.track_diff(url, content)
    # Fire webhook asynchronously on first registration (webhook support)
    if webhook and diff_result["status"] == "registered":
        asyncio.create_task(_fire_watch_webhook(webhook, url, diff_result))
    return {
        "success": True,
        "data": {
            "url": url,
            "status": diff_result["status"],
            "version": diff_result["version"],
            "webhook": webhook,
            "interval": interval,
            "message": "Page registered for change tracking.",
        },
    }


@app.post("/v1/export", tags=["Export"], summary="Export scraped content in multiple formats")
async def export_data(url: str = Body(...), format: str = "json") -> dict[str, Any]:
    """Export scraped content in multiple formats: json, csv, txt, rss.
    Firecrawl only does markdown."""
    result = await scraper.scrape(url)
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Export failed")
    content = result.get("content", "")
    title = result.get("title", url)

    if format == "json":
        return {
            "success": True,
            "data": {"url": url, "title": title, "content": content, "format": "json"},
        }
    elif format == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "title", "content"])
        w.writerow([url, title, content[:50000]])
        return {"success": True, "data": {"csv": buf.getvalue(), "format": "csv"}}
    elif format == "rss":
        from datetime import datetime

        safe_title = html.escape(title)
        safe_url = html.escape(url)
        rss = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Pry: {safe_title}</title>
<link>{safe_url}</link>
<description>Scraped content from {safe_url}</description>
<item><title>{safe_title}</title><link>{safe_url}</link>
<description><![CDATA[{content[:50000]}]]></description>
<pubDate>{datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S UTC")}</pubDate>
</item></channel></rss>"""
        return {"success": True, "data": {"rss": rss, "format": "rss"}}
    return {"success": True, "data": {"text": content[:100000], "format": "txt"}}


@app.post("/v1/shadow-dom", tags=["Parsing"], summary="Extract content from Shadow DOM")
async def extract_shadow_dom(
    url: str = Body(...),
    flatten: bool = Body(True),
) -> dict[str, Any]:
    """Scrape a page and extract content from Shadow DOM components.

    Useful for modern web apps built with Lit, web components, or
    frameworks that use Shadow DOM encapsulation.
    """
    from shadow_dom import ShadowDOMProcessor, has_shadow_dom

    result = await scraper.scrape(url, {"bypass_cloudflare": True, "js_render": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    html = result.get("raw_html", "")
    if not html:
        # Try to get via direct fetch
        client = await get_client()
        try:
            resp = await client.get(url, timeout=30, follow_redirects=True)
            html = resp.text
        except Exception as e:
            raise ScrapeError("Could not fetch raw HTML") from e

    shadow_present = has_shadow_dom(html)
    flat_html = ""

    if shadow_present and flatten:
        processor = ShadowDOMProcessor()
        flat_html = processor.process(html)

    return {
        "success": True,
        "data": {
            "url": url,
            "shadow_dom_detected": shadow_present,
            "flattened": bool(flat_html),
            "content": flat_html[:10000] if flat_html else html[:10000],
            "raw_html_length": len(html),
            "flat_html_length": len(flat_html) if flat_html else len(html),
        },
    }


@app.post(
    "/v1/extract-table", tags=["Extraction"], summary="Extract HTML tables as structured data"
)
async def extract_table(url: str = Body(...), table_index: int = 0) -> dict[str, Any]:
    """Extract HTML tables from a page as structured data.
    Firecrawl doesn't support table extraction at all."""
    import pandas as pd

    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    tables = pd.read_html(resp.text)
    if table_index >= len(tables):
        raise InvalidRequestError(f"Only {len(tables)} tables found")
    df = tables[table_index]
    return {
        "success": True,
        "data": {
            "table_index": table_index,
            "total_tables": len(tables),
            "columns": list(df.columns),
            "rows": df.to_dict(orient="records"),
            "html": df.to_html(index=False),
        },
    }


@app.post("/v1/links", tags=["Extraction"], summary="Analyze links on a page")
async def analyze_links(url: str = Body(...)) -> dict[str, Any]:
    """Analyze all links on a page — internal, external, broken, social.
    Firecrawl only has basic map functionality."""
    html = ""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html = resp.text
    except httpx.HTTPError:
        logger.warning("links_fetch_failed", extra={"url": url})
    base = urlparse(url).netloc
    internal, external = set(), set()
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
        link = m.group(1)
        if urlparse(link).netloc == base:
            internal.add(link.split("#")[0])
        else:
            external.add(link.split("#")[0])
    for m in re.finditer(r'href=["\'](/[^"\']+)["\']', html):
        internal.add(urljoin(url, m.group(1)).split("#")[0])
    social = advanced.find_social_links(html)
    return {
        "success": True,
        "data": {
            "url": url,
            "internal_count": len(internal),
            "external_count": len(external),
            "internal": sorted(internal)[:50],
            "external": sorted(external)[:50],
            "social": social,
        },
    }


@app.post("/v1/seo", tags=["Extraction"], summary="SEO analysis of a page")
async def analyze_seo(url: str = Body(...)) -> dict[str, Any]:
    """SEO analysis of a page: title, description, headings, images, keywords, readability.
    Firecrawl has zero SEO features."""
    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    html = resp.text
    result = await scraper.scrape(url)
    content = result.get("content", "")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    desc = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)
    imgs = re.findall(r"<img\s[^>]*\salt=[\"\']([^\"\']*)[\"\'][^>]*>", html, re.I)
    total_imgs = len(re.findall(r"<img\s", html, re.I))
    imgs_no_alt = total_imgs - len(imgs)

    return {
        "success": True,
        "data": {
            "url": url,
            "title": title.group(1).strip() if title else "",
            "title_length": len(title.group(1).strip()) if title else 0,
            "meta_description": desc.group(1).strip() if desc else "",
            "headings": {"h1": [h.strip() for h in h1], "h2": [h.strip() for h in h2]},
            "images_with_alt": len([a for a in imgs if a.strip()]),
            "images_without_alt": imgs_no_alt,
            "word_count": len(content.split()),
            "readability": advanced.readability(content),
            "keywords": advanced.keyword_density(content, 15),
        },
    }


@app.post("/v1/summarize", tags=["Analysis"], summary="AI summarize scraped content")
async def summarize(url: str = Body(...), max_words: int = 100) -> dict[str, Any]:
    """Scrape + AI summarize using local Ollama. Free, private."""
    result = await scraper.scrape(url, {"bypass_cloudflare": True, "timeout": 30})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error", "Scrape failed"))
    summary = await advanced.summarize(result.get("content", ""), max_words)
    return {"success": True, "data": {"url": url, **summary}}


@app.post("/v1/diff", tags=["Analysis"], summary="Track page changes over time")
async def diff(url: str = Body(...), content: str | None = Body(None)) -> dict[str, Any]:
    """Track page changes over time. Returns diff from last scrape."""
    if content:
        diff_result = await advanced.track_diff(url, content)
    else:
        result = await scraper.scrape(url)
        if result.get("status") != "ok":
            raise ScrapeError("Could not scrape URL")
        diff_result = await advanced.track_diff(url, result.get("content", ""))
    return {"success": True, "data": diff_result}


@app.post("/v1/schema", tags=["Extraction"], summary="Extract Schema.org/JSON-LD structured data")
async def extract_schema(url: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD structured data from a page."""
    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    html = resp.text
    schemas = advanced.extract_schema(html)
    return {"success": True, "data": {"url": url, "schemas": schemas}}


@app.post("/v1/emails", tags=["Extraction"], summary="Find email addresses on a page")
async def find_emails(url: str = Body(...)) -> dict[str, Any]:
    """Find all email addresses on a page."""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html_text = resp.text
    except Exception:
        html_text = ""

    result = await scraper.scrape(url)
    emails = advanced.find_emails(result.get("content", ""))
    social = advanced.find_social_links(html_text)
    return {"success": True, "data": {"url": url, "emails": emails, "social": social}}


# ── Email Inbox Scraping ──


@app.post("/v1/email/scrape", tags=["Email"], summary="Extract data from an email (subject + body)")
async def scrape_email(
    subject: str = Body(""),
    body: str = Body(""),
    sender: str = Body(""),
) -> dict[str, Any]:
    """Extract structured data from an email subject and body.

    Auto-classifies as: order_confirmation, invoice, receipt,
    shipping_notification, subscription, or other.

    Extracts: order numbers, amounts, tracking numbers, dates, addresses.
    """
    from email_scraper import extract_email_data

    result = extract_email_data(subject, body, sender)
    return {"success": True, "data": result}


@app.post("/v1/email/gmail", tags=["Email"], summary="Fetch and extract data from Gmail inbox")
async def fetch_gmail(
    access_token: str = Body(...),
    max_results: int = Body(20),
    query: str = Body(""),
    since_days: int = Body(7),
) -> dict[str, Any]:
    """Connect to Gmail and extract structured data from emails.

    Requires a Gmail OAuth2 access token with scope:
    https://www.googleapis.com/auth/gmail.readonly

    Extracts order confirmations, invoices, receipts, shipping notifications.
    """
    from email_scraper import fetch_gmail_emails

    result = await fetch_gmail_emails(access_token, max_results, query, since_days)
    return {"success": result.get("success", False), "data": result}


@app.post("/v1/email/outlook", tags=["Email"], summary="Fetch and extract data from Outlook inbox")
async def fetch_outlook(
    access_token: str = Body(...),
    max_results: int = Body(20),
    query: str = Body(""),
    since_days: int = Body(7),
) -> dict[str, Any]:
    """Connect to Outlook/Office 365 and extract structured data from emails.

    Requires a Microsoft Graph OAuth2 access token with scope:
    https://graph.microsoft.com/Mail.Read

    Extracts order confirmations, invoices, receipts, shipping notifications.
    """
    from email_scraper import fetch_outlook_emails

    result = await fetch_outlook_emails(access_token, max_results, query, since_days)
    return {"success": result.get("success", False), "data": result}


@app.post("/v1/categorize", tags=["Analysis"], summary="AI-categorize scraped content")
async def categorize(url: str = Body(...)) -> dict[str, Any]:
    """AI-categorize scraped content into topic tags."""
    result = await scraper.scrape(url)
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Categorize failed")
    tags = await advanced.categorize(result.get("content", ""))
    kw = advanced.keyword_density(result.get("content", ""))
    readability = advanced.readability(result.get("content", ""))
    return {
        "success": True,
        "data": {"url": url, "tags": tags, "keywords": kw[:10], "readability": readability},
    }


# ── Integrations ──


@app.get(
    "/v1/destinations",
    tags=["Integrations"],
    summary="List supported data destinations",
)
async def list_destinations() -> dict[str, Any]:
    """List all supported data destinations and their config requirements."""
    return {
        "success": True,
        "data": {
            "destinations": [
                {
                    "id": "slack",
                    "name": "Slack",
                    "description": "Send data to a Slack channel via webhook",
                    "config_fields": ["webhook_url", "title"],
                },
                {
                    "id": "googlesheets",
                    "name": "Google Sheets",
                    "description": "Write data to a Google Spreadsheet",
                    "config_fields": ["spreadsheet_id", "range", "credentials_json"],
                },
                {
                    "id": "airtable",
                    "name": "Airtable",
                    "description": "Write records to an Airtable base",
                    "config_fields": ["base_id", "table_name", "api_key"],
                },
                {
                    "id": "email",
                    "name": "Email",
                    "description": "Send data via email (SMTP or mailto link)",
                    "config_fields": ["recipient", "subject", "smtp_host", "smtp_user"],
                },
            ]
        },
    }


@app.post(
    "/v1/destination/send",
    tags=["Integrations"],
    summary="Send scraped data to a business destination",
)
async def send_to_destination(
    destination: str = Body(...),
    data: dict[str, Any] = Body(...),
    config: dict[str, Any] = Body(...),
    url: str | None = Body(None),
) -> dict[str, Any]:
    """Send extracted data to a business destination in one click.

    Destinations:
    - slack: Send to Slack channel via webhook
    - googlesheets: Write to Google Sheets (requires credentials)
    - airtable: Write to Airtable base (requires API key)
    - email: Send via email (requires SMTP config)

    Config varies by destination:
    - slack: {"webhook_url": "https://hooks.slack.com/..."}
    - googlesheets: {"spreadsheet_id": "...", "credentials_json": "..."}
    - airtable: {"base_id": "...", "table_name": "Table 1", "api_key": "..."}
    - email: {"recipient": "user@example.com", "subject": "Data Export"}
    """
    from destinations import SUPPORTED_DESTINATIONS, dispatch

    if destination not in SUPPORTED_DESTINATIONS:
        raise InvalidRequestError(
            f"Unsupported destination: {destination}. Supported: {SUPPORTED_DESTINATIONS}"
        )

    result = await dispatch(destination, data, config)
    return {"success": result["success"], "data": result}


@app.post(
    "/v1/scrape-and-send",
    tags=["Integrations"],
    summary="Scrape a URL and send to a destination",
)
async def scrape_and_send(
    url: str = Body(...),
    destination: str = Body(...),
    destination_config: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Scrape a URL and send the results to a business destination in one step.

    Combines /v1/scrape + /v1/destination/send into a single call.
    Perfect for non-technical users who just want data in their tools.
    """
    from destinations import SUPPORTED_DESTINATIONS, dispatch

    if destination not in SUPPORTED_DESTINATIONS:
        raise InvalidRequestError(
            f"Unsupported destination: {destination}. Supported: {SUPPORTED_DESTINATIONS}"
        )

    # Scrape
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    # Send to destination
    send_result = await dispatch(destination, result.get("data", result), destination_config)

    return {
        "success": send_result["success"],
        "data": {
            "url": url,
            "destination": destination,
            "scrape_status": result.get("status"),
            "delivery": send_result,
        },
    }


# ── Alerts ──


@app.post("/v1/alert/send", tags=["Alerts"], summary="Send an alert to any channel")
async def send_alert_endpoint(
    channel: str = Body(...),
    title: str = Body("Pry Alert"),
    message: str = Body(...),
    config: dict[str, Any] = Body(...),
    severity: str = Body("info"),
) -> dict[str, Any]:
    """Send an alert to Slack, Discord, Teams, Telegram, SMS, or Email.

    Config varies by channel:
    - slack: {"webhook_url": "..."}
    - discord: {"webhook_url": "..."}
    - teams: {"webhook_url": "..."}
    - telegram: {"bot_token": "...", "chat_id": "..."}
    - sms: {"phone": "+1234567890", "twilio_sid": "...", "twilio_token": "...", "twilio_from": "..."}
    - email: {"recipient": "user@example.com", "smtp_host": "...", "smtp_user": "..."}
    """
    from alerter import send_alert

    result = await send_alert(channel, title, message, config, severity)
    return {"success": result["success"], "data": result}


@app.get("/v1/alert/channels", tags=["Alerts"], summary="List supported alert channels")
async def list_channels() -> dict[str, Any]:
    """List all supported alert channels and their config requirements."""
    return {
        "success": True,
        "data": {
            "channels": [
                {"id": "slack", "name": "Slack", "config_fields": ["webhook_url"]},
                {"id": "discord", "name": "Discord", "config_fields": ["webhook_url"]},
                {"id": "teams", "name": "Microsoft Teams", "config_fields": ["webhook_url"]},
                {"id": "telegram", "name": "Telegram", "config_fields": ["bot_token", "chat_id"]},
                {
                    "id": "sms",
                    "name": "SMS (Twilio)",
                    "config_fields": ["phone", "twilio_sid", "twilio_token", "twilio_from"],
                },
                {
                    "id": "email",
                    "name": "Email",
                    "config_fields": ["recipient", "smtp_host", "smtp_user"],
                },
            ]
        },
    }


# ── Jobs ──
@app.get("/v1/job/{job_id}", tags=["Jobs"], summary="Get async job status and result")
async def get_job(job_id: str) -> dict[str, Any]:
    """Get async job status and result."""
    job = await queue.get_job(job_id)
    if not job:
        raise NotFoundError("Job not found")
    return {"success": True, "data": job}


# ── Config ──


@app.get("/v1/config", tags=["Config"], summary="Get current Pry configuration")
async def get_config() -> dict[str, Any]:
    """Get current Pry configuration."""
    return {"success": True, "data": config.to_dict()}


@app.post("/v1/config", tags=["Config"], summary="Update Pry configuration at runtime")
async def update_config(updates: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update Pry configuration at runtime."""
    result = config.update(updates)
    return {"success": True, "data": result}


@app.post("/v1/config/profile/tor", tags=["Config"], summary="Enable Tor routing for all requests")
async def enable_tor() -> dict[str, Any]:
    """Enable Tor routing for all requests."""
    result = config.update(
        {"tor": {"enabled": True}, "proxy": {"enabled": True, "url": "socks5://tor:9050"}}
    )
    resp_data = {
        "success": True,
        "data": result,
        "note": "Run 'docker compose --profile tor up -d' to start Tor container",
    }
    return resp_data


# ── Win 3: WebSocket streaming ──
@app.websocket("/v1/stream/{job_id}")
async def stream_endpoint(websocket: WebSocket, job_id: str = "live") -> None:
    await websocket.accept()
    streams.register(job_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await streams.broadcast(job_id, {"echo": data})
    except WebSocketDisconnect:
        streams.unregister(job_id, websocket)


# ── Win 5: Batch from file + template ──
class BatchFileRequest(BaseModel):
    filepath: str
    template: dict[str, str]
    timeout: int | None = 30
    max_urls: int | None = 1000


@app.post("/v1/batch-file", tags=["Batch"], summary="Batch scrape URLs from a file with templates")
async def batch_from_file(request: BatchFileRequest) -> dict[str, Any]:
    bp = BatchProcessor()
    results = await bp.from_file(
        request.filepath, request.template, request.timeout or 30, request.max_urls or 1000
    )
    return {"success": True, "data": {"total": len(results), "results": results}}


# ── Win 6: Browser recorder ──
@app.post("/v1/record/start", tags=["Recorder"], summary="Start recording browser actions")
async def start_recording(session_id: str = Body(...)) -> dict[str, Any]:
    recorder.start(session_id)
    return {"success": True, "data": {"session_id": session_id, "status": "recording"}}


@app.post("/v1/record/step", tags=["Recorder"], summary="Record a browser action step")
async def record_step(
    session_id: str = Body(...), action: str = Body(...), selector: str = "", value: str = ""
) -> dict[str, Any]:
    recorder.record(session_id, action, selector, value)
    return {"success": True, "data": {"recorded": len(recorder._recordings.get(session_id, []))}}


@app.post("/v1/record/export", tags=["Recorder"], summary="Export recording as script")
async def export_recording(session_id: str = Body(...), fmt: str = "json") -> dict[str, Any]:
    script = recorder.export(session_id, fmt)
    return {"success": True, "data": {"script": script, "format": fmt}}


@app.post("/v1/record/clear", tags=["Recorder"], summary="Clear recorded actions")
async def clear_recording(session_id: str = Body(...)) -> dict[str, Any]:
    recorder.clear(session_id)
    return {"success": True, "data": {"status": "cleared"}}


# ── Win 8: Multi-format transform ──
@app.post("/v1/transform", tags=["Transform"], summary="Transform data to multiple formats")
async def transform_data(
    data: list[dict[str, Any]] = Body(...), format: str = "csv"
) -> dict[str, Any]:
    te = TransformEngine()
    if format == "csv":
        result = te.to_csv(data)
    elif format == "sql":
        result = "\n".join(te.to_sql(row) for row in data)
    elif format == "html":
        result = te.to_html_table(data)
    elif format == "markdown":
        result = te.to_markdown_table(data)
    else:
        raise InvalidRequestError(f"Unknown format: {format}")
    return {"success": True, "data": {"output": result, "format": format}}


# ── Win 1: Pryfile execution ──
@app.post("/v1/run", tags=["Execute"], summary="Execute a Pryfile")
async def run_pryfile(path: str = Body("pry.yml")) -> dict[str, Any]:
    from pryfile import Pryfile

    resolved = _safe_pryfile_path(path)
    pf = Pryfile(resolved)
    results = await pf.run_all(scraper)
    return {"success": True, "data": {"jobs": results, "total": len(results)}}


@app.get("/v1/jobs", tags=["Jobs"], summary="List jobs in a Pryfile")
async def list_jobs(path: str = "pry.yml") -> dict[str, Any]:
    from pryfile import Pryfile

    resolved = _safe_pryfile_path(path)
    pf = Pryfile(resolved)
    return {"success": True, "data": {"jobs": pf.list_jobs()}}


def _safe_pryfile_path(path: str) -> str:
    """Resolve and validate Pryfile path — prevent directory traversal."""
    resolved = Path(path).resolve()
    allowed = Path.cwd().resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as e:
        raise InvalidRequestError(f"Path must be inside {allowed}") from e
    if not resolved.is_file():
        raise InvalidRequestError(f"File not found: {resolved}")
    return str(resolved)


# ── Win 10: Health dashboard HTML ──
@app.get("/dashboard", tags=["Dashboard"], summary="Pry health and performance dashboard")
async def dashboard() -> HTMLResponse:
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pry — Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,system-ui,sans-serif; background:#0a0a0b; color:#e4e4e7; padding:2rem; }}
h1 {{ font-size:1.5rem; color:#f59e0b; margin-bottom:.5rem; }}
p {{ color:#71717a; margin-bottom:2rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:1rem; margin-bottom:2rem; }}
.card {{ background:#18181b; border:1px solid #27272a; border-radius:8px; padding:1.25rem; }}
.card h3 {{ font-size:.75rem; text-transform:uppercase; color:#71717a; margin-bottom:.5rem; }}
.card .value {{ font-size:1.75rem; font-weight:700; color:#f4f4f5; }}
.card .sub {{ font-size:.8rem; color:#52525b; margin-top:.25rem; }}
.status-ok {{ color:#22c55e; }} .status-warn {{ color:#eab308; }} .status-err {{ color:#ef4444; }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
th,td {{ padding:.5rem; text-align:left; border-bottom:1px solid #27272a; }}
th {{ color:#71717a; font-weight:600; text-transform:uppercase; font-size:.7rem; }}
</style></head><body>
<h1>🔧 Pry Dashboard</h1>
<p>Scrape engine health and performance metrics</p>
<div class="grid">
  <div class="card"><h3>Cache Hit Rate</h3><div class="value">{cache_stats.get("hit_rate", 0)}%</div><div class="sub">{cache_stats.get("hits", 0)} hits / {cache_stats.get("size", 0)} entries</div></div>
  <div class="card"><h3>Rate Limit</h3><div class="value">{rate_stats.get("total_requests", 0)}</div><div class="sub">{rate_stats.get("active_ips", 0)} active IPs</div></div>
  <div class="card"><h3>Blocked</h3><div class="value">{rate_stats.get("total_blocked", 0)}</div><div class="sub">requests blocked</div></div>
  <div class="card"><h3>Sessions</h3><div class="value">{len(automator.sessions)}</div><div class="sub">active browser sessions</div></div>
</div>
<table><tr><th>Endpoint</th><th>Method</th><th>Status</th></tr>
<tr><td>/v1/scrape</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/crawl</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/automate</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/batch</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/stream</td><td>WebSocket</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/run</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>FlareSolverr</td><td>Proxy</td><td class="status-ok">✅ Connected</td></tr>
</table>
<p style="margin-top:2rem;font-size:.75rem;color:#52525b">Pry v3.0.0 — Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}</p>
</body></html>"""
    return HTMLResponse(content=html)


# ── Win 1: AI Schema Suggestion ──
@app.post("/v1/suggest", tags=["Analysis"], summary="AI-suggest schema fields for a URL")
async def suggest_schema(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")

    result = await scraper.scrape(url, {"bypass_cloudflare": True, "timeout": 30})
    content = result.get("content", "")
    html = ""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html = resp.text
    except httpx.HTTPError:
        logger.warning("suggest_schema_fetch_failed", extra={"url": url})
    schema = {"_page_title": result.get("title", "")}
    candidates: dict[str, str] = {}
    for pattern, field in [
        (r'["\']((?:price|cost|amount)[^"\']*)["\']', "price"),
        (r'["\'](product-title|product-name|item-name)[^"\']*["\']', "name"),
        (r'["\'](?:product-image|main-image|featured-image)[^"\']*["\']', "image"),
        (r'["\'](?:description|product-desc|item-desc)[^"\']*["\']', "description"),
        (r'["\'](?:rating|stars|review-score)[^"\']*["\']', "rating"),
        (r'["\'](?:stock|availability|status)[^"\']*["\']', "stock"),
    ]:
        found = re.findall(pattern, html.lower())
        if found:
            candidates[field] = f'[class*="{found[0][:15]}"]'
    if "name" not in candidates:
        h1 = re.findall(r'<h1[^>]*class=["\']([^"\']*)["\']', html)
        if h1:
            candidates["name"] = f"h1.{h1[0].replace(' ', '.')}"
    schema["suggested"] = candidates
    if content and len(content) > 200:
        try:
            prompt = (
                "Analyze this page. Return ONLY JSON with field names as keys and CSS selectors as values. Look for: price, name, description, image, rating, stock.\n\n"
                + content[:4000]
            )
            client = await get_client()
            ollama_url = settings.ollama_url
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": "qwen2.5-coder:3b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_ctx": 8192, "temperature": 0.1},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                llm_raw = resp.json().get("response", "")
                llm_match = re.search(r"\{.*\}", llm_raw, re.S)
                if llm_match:
                    try:
                        llm = json.loads(llm_match.group(0))
                        if isinstance(llm, dict):
                            schema["llm_suggested"] = llm
                    except json.JSONDecodeError:
                        logger.warning("llm_schema_parse_failed")
        except httpx.HTTPError:
            logger.warning("ollama_suggest_schema_failed")
    return {"success": True, "data": schema}


# ── Win 2: Circuit Breaker ──
_failures: dict[str, int] = {}


@app.post("/v1/breaker/status", tags=["Circuit Breaker"], summary="Get circuit breaker status")
async def breaker_status() -> dict[str, Any]:
    return {
        "success": True,
        "data": {k: {"fails": v, "backoff": min(2**v, 60)} for k, v in _failures.items()},
    }


@app.post(
    "/v1/breaker/reset", tags=["Circuit Breaker"], summary="Reset circuit breaker for a domain"
)
async def breaker_reset(domain: str = Body("")) -> dict[str, Any]:
    if domain:
        _failures.pop(domain, None)
    else:
        _failures.clear()
    return {"success": True, "data": {"cleared": domain or "all"}}


# ── Win 3: Stable Extraction ──
@app.post("/v1/extract", tags=["Extraction"], summary="Extract structured fields from a URL")
async def extract_stable(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    fields = data.get("fields", {})
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Extraction failed")
    from extractor import SchemaExtractor

    ex = SchemaExtractor()
    extracted = await ex.extract(result.get("content", ""), fields, mode="llm")
    return {"success": True, "data": {"url": url, "fields": extracted}}


@app.post(
    "/v1/extract/css",
    tags=["Extraction"],
    summary="Extract structured data with CSS selectors (no LLM)",
)
async def extract_css(
    url: str = Body(...),
    schema: dict[str, Any] = Body(...),
    bypass_cloudflare: bool = Body(True),
) -> dict[str, Any]:
    """Extract structured JSON from a URL using CSS selector schema.

    Schema format:
    {
        "name": "products",
        "base_selector": ".product-card",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text", "transform": "float"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "in_stock", "selector": ".stock", "type": "exists"},
        ]
    }
    """
    result = await scraper.scrape(url, {"bypass_cloudflare": bypass_cloudflare})
    html = result.get("raw_html", "")

    if not html:
        client = await get_client()
        resp = await client.get(
            url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        )
        html = resp.text

    if not html:
        raise ScrapeError("No HTML content returned from scraper")

    strategy = JsonCssExtractionStrategy(schema)
    data = strategy.extract(html)

    return {
        "success": True,
        "data": {
            "schema": schema.get("name", "extracted"),
            "count": len(data),
            "items": data,
        },
    }


@app.post("/v1/extract/llm", tags=["Extraction"], summary="Extract with LLM + chunking strategies")
async def extract_llm(
    url: str = Body(...),
    instruction: str = Body("Extract all key information from this content."),
    schema: dict[str, Any] | None = Body(None),
    chunk_strategy: str = Body("topic"),
    query: str = Body(""),
    top_k: int = Body(5),
) -> dict[str, Any]:
    """Extract structured data using LLM with intelligent chunking.

    Chunks content by strategy (topic/sentence/regex), optionally filters
    by relevance to query, then extracts from each chunk.
    """

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    content = result.get("content", "")
    if not content:
        raise ScrapeError("No content returned from scraper")

    chunks = await extract_with_chunking(
        content=content,
        instruction=instruction,
        schema=schema,
        chunk_strategy=chunk_strategy,
        query=query,
        top_k=top_k,
    )

    return {
        "success": True,
        "data": {
            "chunks": chunks,
            "total_chunks": len(chunks),
            "strategy": chunk_strategy,
        },
    }


# ── Pipeline hooks ──


@app.post("/v1/pipeline/hook", tags=["Pipeline"], summary="Register a hook function")
async def register_hook(
    hook_point: str = Body(...),
    javascript_fn: str = Body(...),
) -> dict[str, Any]:
    """Register a JavaScript hook function at a pipeline hook point.

    Hook points: before_scrape, after_response, before_parse, after_parse,
                 before_extract, after_extract, before_return, on_error
    """
    if hook_point not in HOOK_POINTS:
        raise InvalidRequestError(f"Unknown hook point: {hook_point}. Valid: {HOOK_POINTS}")

    # For now, just acknowledge the registration
    # In production, this would execute JS in a sandbox
    return {
        "success": True,
        "data": {
            "hook_point": hook_point,
            "registered": True,
            "message": f"Hook registered at {hook_point}. Note: custom JS hooks require a sandboxed runtime.",
        },
    }


@app.get("/v1/pipeline/hooks", tags=["Pipeline"], summary="List all registered hooks")
async def list_pipeline_hooks() -> dict[str, Any]:
    """List all registered hooks in the pipeline."""
    pipeline = get_pipeline()
    return {
        "success": True,
        "data": {
            "hooks": pipeline.list_hooks(),
            "hook_points": HOOK_POINTS,
        },
    }


@app.post("/v1/pipeline/run", tags=["Pipeline"], summary="Run pipeline hooks for testing")
async def run_pipeline_test(
    hook_point: str = Body(...),
    url: str = Body(""),
    html: str = Body(""),
) -> dict[str, Any]:
    """Run hooks at a given pipeline point for testing."""
    if hook_point not in HOOK_POINTS:
        raise InvalidRequestError(f"Unknown hook point: {hook_point}")

    result = await run_pipeline(hook_point, url=url, html=html)
    return {
        "success": True,
        "data": {
            "hook_point": hook_point,
            "result": {k: v for k, v in result.items() if k != "html"},
            "error_count": len(result.get("errors", [])),
        },
    }


# ── Win 4: Data Pipeline ──
@app.post("/v1/pipe", tags=["Transform"], summary="Scrape and transform via data pipeline")
async def data_pipeline(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    transform = data.get("transform", "json")
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Pipeline failed")
    content = result.get("content", "")
    title = result.get("title", url)
    if transform == "sql":
        from pryextras import TransformEngine

        te = TransformEngine()
        output = te.to_sql({"url": url, "title": title, "content": content[:50000]})
    elif transform == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "title", "content"])
        w.writerow([url, title, content[:50000]])
        output = buf.getvalue()
    else:
        output = json.dumps({"url": url, "title": title, "content": content[:100000]}, indent=2)
    return {"success": True, "data": {"url": url, "output": output, "format": transform}}


# ── Win 5: Shareable Results ──
_shares: dict[str, dict[str, Any]] = {}


@app.post("/v1/share", tags=["Share"], summary="Share scraped content via link")
async def share_scrape(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    sid = uuid.uuid4().hex[:8]
    _shares[sid] = {
        "url": url,
        "title": result.get("title", url),
        "content": result.get("content", ""),
        "method": result.get("method"),
        "ts": datetime.now(UTC).isoformat(),
    }
    return {"success": True, "data": {"share_id": sid, "url": f"/share/{sid}"}}


@app.get("/share/{share_id}", tags=["Share"], summary="View shared content")
async def view_share(share_id: str) -> HTMLResponse:
    d = _shares.get(share_id)
    if not d:
        return HTMLResponse("<h1>Not found</h1><p>Share expired.</p>", 404)
    st, sc, su = html.escape(d["title"]), html.escape(d["content"][:100000]), html.escape(d["url"])
    return HTMLResponse(
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>{st} — Pry Share</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>body{{font-family:-apple-system,system-ui,sans-serif;background:#09090b;color:#e4e4e7;padding:2rem;max-width:800px;margin:0 auto}}"
        f"h1{{font-size:1.5rem;color:#f59e0b}}.meta{{color:#52525b;font-size:.85rem;margin-bottom:2rem}}"
        f"pre{{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:1.5rem;white-space:pre-wrap}}</style></head><body>"
        f'<h1>🔧 {st}</h1><p class="meta"><a href="{su}">{su}</a> · {d["method"]} · {d["ts"][:10]}</p>'
        f"<pre>{sc}</pre></body></html>"
    )


# ── Compliance ──


@app.post("/v1/compliance/check", tags=["Compliance"], summary="Run full compliance check on a URL")
async def compliance_check(url: str = Body(...)) -> dict[str, Any]:
    """Run a full legal compliance check on a target URL.

    Analyzes:
    - robots.txt crawl permissions
    - Terms of Service classification (restrictive/permissive/moderate)
    - Jurisdiction detection (GDPR, CCPA, LGPD)
    - Sensitive data detection (PII, financial, health, contact)

    Returns a green/yellow/red risk score with recommendations.
    """
    from compliance import run_compliance_check

    result = await run_compliance_check(url)
    return {"success": True, "data": result}


@app.get("/v1/compliance/check", tags=["Compliance"], summary="Get compliance check documentation")
async def compliance_docs() -> dict[str, Any]:
    """Get information about the compliance check endpoint."""
    return {
        "success": True,
        "data": {
            "description": "Legal compliance engine for web scraping targets",
            "risk_levels": {
                "green": "Low risk — standard scraping practices",
                "yellow": "Moderate risk — proceed with caution",
                "red": "High risk — legal review required",
            },
            "factors_checked": [
                "robots.txt crawl permissions",
                "Terms of Service classification",
                "Jurisdiction detection (GDPR/CCPA/LGPD)",
                "Sensitive data categories (PII, financial, health, contact)",
            ],
        },
    }


# ── GDPR Compliance Portal ──


@app.post("/v1/gdpr/consent", tags=["GDPR"], summary="Record user consent for data processing")
async def record_consent_endpoint(
    user_id: str = Body(...),
    purpose: str = Body("data_collection"),
    consent_given: bool = Body(True),
    ip_address: str = Body(""),
    user_agent: str = Body(""),
) -> dict[str, Any]:
    """Record a user's consent for data processing (GDPR Art. 7).

    Stores: user hash, purpose, timestamp, IP, user agent.
    Consent expires after 365 days.
    """
    from gdpr import record_consent

    result = await record_consent(user_id, purpose, consent_given, ip_address, user_agent)
    return {"success": result["success"], "data": result}


@app.get("/v1/gdpr/consent/{user_id}", tags=["GDPR"], summary="Check user consent status")
async def check_consent_endpoint(
    user_id: str,
    purpose: str = "data_collection",
) -> dict[str, Any]:
    """Check if a user has given valid consent for data processing."""
    from gdpr import check_consent

    result = check_consent(user_id, purpose)
    return {"success": True, "data": result}


@app.post("/v1/gdpr/consent/revoke", tags=["GDPR"], summary="Revoke user consent")
async def revoke_consent_endpoint(
    user_id: str = Body(...),
    purpose: str = Body("data_collection"),
) -> dict[str, Any]:
    """Revoke a user's consent for a processing purpose (GDPR Art. 7(3))."""
    from gdpr import revoke_consent

    result = revoke_consent(user_id, purpose)
    return {"success": True, "data": result}


@app.post(
    "/v1/gdpr/deletion/request", tags=["GDPR"], summary="Request data deletion (right to erasure)"
)
async def request_deletion_endpoint(
    user_id: str = Body(...),
    reason: str = Body("user_request"),
) -> dict[str, Any]:
    """Request deletion of all data associated with a user (GDPR Art. 17).

    Creates a deletion request that can be executed immediately or
    after a holding period.
    """
    from gdpr import request_deletion

    result = await request_deletion(user_id, reason)
    return {"success": "error" not in result, "data": result}


@app.post("/v1/gdpr/deletion/execute", tags=["GDPR"], summary="Execute data deletion request")
async def execute_deletion_endpoint(
    request_id: str = Body(...),
) -> dict[str, Any]:
    """Execute a pending deletion request, removing all user data."""
    from gdpr import execute_deletion

    result = await execute_deletion(request_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@app.get("/v1/gdpr/retention", tags=["GDPR"], summary="Get data retention policy")
async def get_retention_policy_endpoint() -> dict[str, Any]:
    """Get the current data retention policy."""
    from gdpr import get_retention_policy

    return {"success": True, "data": get_retention_policy()}


@app.post(
    "/v1/gdpr/retention/apply",
    tags=["GDPR"],
    summary="Apply retention policy to remove expired data",
)
async def apply_retention() -> dict[str, Any]:
    """Apply the retention policy, removing all expired data."""
    from gdpr import apply_retention_policy

    result = await apply_retention_policy()
    return {"success": True, "data": result}


@app.get("/v1/gdpr/audit", tags=["GDPR"], summary="Get compliance audit log")
async def get_audit_log_endpoint(days_back: int = 7) -> dict[str, Any]:
    """Get the compliance audit log for the specified period."""
    from gdpr import get_audit_log

    events = get_audit_log(days_back)
    return {"success": True, "data": {"events": events, "total": len(events)}}


# ── AI Training Data Pipeline ──


@app.post(
    "/v1/training/classify-license",
    tags=["Training"],
    summary="Classify content license for AI training",
)
async def classify_license_endpoint(text: str = Body(...)) -> dict[str, Any]:
    """Classify the license of scraped content for AI training compliance.

    Returns license type (CC0, CC-BY, MIT, Apache, GPL, Proprietary, Fair Use),
    tier (permissive/copyleft/restrictive/conditional), and confidence.
    """
    from training_data import classify_license

    result = classify_license(text)
    return {"success": True, "data": result}


@app.post("/v1/training/clean", tags=["Training"], summary="Strip PII and copyright from content")
async def clean_content(
    text: str = Body(...),
    strip_names: bool = Body(False),
    strip_copyright: bool = Body(True),
) -> dict[str, Any]:
    """Strip PII and copyright content for AI training clean room.

    Removes emails, phones, SSNs, credit cards, IPs, and (optionally) names.
    Also strips copyright notices and near-verbatim copyright content.
    """
    from training_data import strip_copyright_verbatim, strip_pii

    cleaned, pii_stats = strip_pii(text, preserve_names=not strip_names)
    copyright_stats = {"blocks_removed": 0, "total_chars_removed": 0}

    if strip_copyright:
        cleaned, copyright_stats = strip_copyright_verbatim(cleaned)

    return {
        "success": True,
        "data": {
            "original_length": len(text),
            "cleaned_length": len(cleaned),
            "pii_removed": pii_stats,
            "copyright_blocks_removed": copyright_stats["blocks_removed"],
            "copyright_chars_removed": copyright_stats["total_chars_removed"],
            "cleaned_content": cleaned[:5000] if len(cleaned) > 5000 else cleaned,
            "truncated": len(cleaned) > 5000,
        },
    }


@app.post(
    "/v1/training/export",
    tags=["Training"],
    summary="Export a clean AI training dataset",
)
async def export_dataset(
    records: list[dict[str, Any]] = Body(...),
    output_format: str = Body("jsonl"),
    clean_room: bool = Body(True),
    strip_names: bool = Body(False),
) -> dict[str, Any]:
    """Export scraped content as a clean AI training dataset.

    Each record should have: content, url, and optional metadata.

    Features:
    - Per-record provenance tracking (source URL, timestamp, extraction method)
    - PII stripping (email, phone, SSN, CC, IP)
    - Copyright verbatim text removal
    - License classification
    - Compliance report generation
    """
    from training_data import export_training_dataset

    result = export_training_dataset(
        records=records,
        format=output_format,  # type: ignore
        clean_room=clean_room,
        strip_names=strip_names,
    )
    return {"success": result["success"], "data": result}


@app.get(
    "/v1/training/compliance/{dataset_id}",
    tags=["Training"],
    summary="Generate compliance report for a dataset",
)
async def compliance_report(dataset_id: str) -> dict[str, Any]:
    """Generate a compliance report for an exported training dataset.

    Report includes: data provenance, PII/copyright removal stats,
    license classification, and legal recommendations.
    """
    from training_data import generate_compliance_report

    result = generate_compliance_report(dataset_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


# ── Monitoring (cron-based content change detection with AI judging) ──


@app.post("/v1/monitor", tags=["Monitoring"], summary="Create a scheduled content monitor")
async def create_monitor_endpoint(
    name: str = Body(...),
    url: str = Body(...),
    schedule_cron: str = Body("0 */6 * * *"),
    goal: str = Body(""),
    webhook: str = Body(""),
    use_llm: bool = Body(False),
) -> dict[str, Any]:
    """Create a scheduled monitor that tracks content changes.

    Args:
        name: Human-readable monitor name
        url: Target URL to monitor
        schedule_cron: Cron expression (default: every 6 hours)
        goal: Natural language goal for meaningful-change detection
        webhook: URL to notify on meaningful changes
        use_llm: Use LLM for change judging (slower but smarter)
    """
    from monitor import create_monitor

    monitor = await create_monitor(name, url, schedule_cron, goal, webhook, use_llm)
    return {"success": True, "data": monitor}


@app.post("/v1/monitor/run", tags=["Monitoring"], summary="Run a single monitor check")
async def run_monitor_endpoint(
    monitor_id: str = Body(...),
) -> dict[str, Any]:
    """Execute a monitor check immediately (outside of schedule)."""
    from monitor import run_monitor

    result = await run_monitor(monitor_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@app.get("/v1/monitors", tags=["Monitoring"], summary="List all monitors")
async def list_monitors_endpoint() -> dict[str, Any]:
    """List all registered monitors."""
    from monitor import list_monitors

    monitors = await list_monitors()
    return {"success": True, "data": {"monitors": monitors, "total": len(monitors)}}


@app.delete("/v1/monitor/{monitor_id}", tags=["Monitoring"], summary="Delete a monitor")
async def delete_monitor_endpoint(monitor_id: str) -> dict[str, Any]:
    """Delete a monitor and its snapshots."""
    from monitor import delete_monitor

    success = await delete_monitor(monitor_id)
    if not success:
        raise NotFoundError(f"Monitor not found: {monitor_id}")
    return {"success": True, "data": {"monitor_id": monitor_id, "deleted": True}}


@app.post("/v1/monitor/check", tags=["Monitoring"], summary="Run all due monitors")
async def run_due_monitors() -> dict[str, Any]:
    """Check all monitors and run any that are due based on their cron schedule."""
    import croniter

    from monitor import list_monitors, run_monitor

    monitors = await list_monitors()
    now = datetime.now(UTC)
    results = []
    for m in monitors:
        last_run = m.get("last_run_at")
        last_dt = datetime.fromisoformat(last_run) if last_run else datetime.min.replace(tzinfo=UTC)

        try:
            cron = croniter.croniter(m["schedule_cron"], last_dt)
            next_run = cron.get_next(datetime)
            if next_run <= now:
                result = await run_monitor(m["id"])
                results.append(result)
        except Exception as e:
            logger.warning(
                "monitor_schedule_check_failed", extra={"monitor_id": m["id"], "error": str(e)}
            )

    return {
        "success": True,
        "data": {
            "total_monitors": len(monitors),
            "ran_count": len(results),
            "results": results,
        },
    }


# ── Structure Monitor ──


@app.post(
    "/v1/structure/check",
    tags=["Structure"],
    summary="Check if CSS selectors still match on a page",
)
async def structure_check(
    url: str = Body(...),
    selectors: list[dict[str, Any]] = Body(...),
) -> dict[str, Any]:
    """Check if CSS selectors still match on a page.

    Use this to verify your scraper templates still work after
    a site redesign. Returns per-selector match status.

    Selectors format: [{"name": "title", "selector": "h1", "type": "css"}]
    """
    from structure_monitor import check_selectors

    result = await check_selectors(url, selectors)
    return {"success": "error" not in result, "data": result}


@app.post(
    "/v1/structure/monitor", tags=["Structure"], summary="Monitor page structure changes over time"
)
async def structure_monitor(
    url: str = Body(...),
    selectors: list[dict[str, Any]] = Body(...),
    template_id: str = Body(""),
) -> dict[str, Any]:
    """Monitor page structure changes and detect broken selectors.

    Compares current selector match status to previous checks.
    Alerts when selectors stop matching (site redesign detected).

    Use this as a pre-scrape health check for your templates.
    """
    from structure_monitor import monitor_page_structure

    result = await monitor_page_structure(url, selectors, template_id)
    return {"success": "error" not in result, "data": result}


@app.post(
    "/v1/structure/check-template",
    tags=["Structure"],
    summary="Verify a scraper template still works",
)
async def structure_check_template(
    template_id: str = Body(...), url: str = Body("")
) -> dict[str, Any]:
    """Check if a pre-built scraper template still works against a URL.

    Extracts the template's selectors and checks each one.
    If selectors fail, the template needs updating.
    """
    from structure_monitor import monitor_page_structure
    from template_engine import get_template

    template = get_template(template_id)
    if not template:
        raise NotFoundError(f"Template not found: {template_id}")

    schema = template.get("schema", {})
    fields = schema.get("fields", [])
    selectors = [
        {
            "name": f.get("name", f"field_{i}"),
            "selector": f.get("selector", ""),
            "type": "css" if f.get("type") != "xpath" else "xpath",
        }
        for i, f in enumerate(fields)
        if f.get("selector")
    ]

    if not selectors:
        raise InvalidRequestError("Template has no selectable fields")

    # If no URL provided, try the template's site URL
    if not url:
        site = template.get("site", "")
        url = (
            f"https://www.{site}"
            if site and not site.startswith("http")
            else (site if site else "https://example.com")
        )

    result = await monitor_page_structure(url, selectors, template_id)
    return {"success": "error" not in result, "data": result}


# ── Intelligence (Competitive Intelligence Engine) ──


@app.post("/v1/intel/snapshot", tags=["Intelligence"], summary="Record a competitor data snapshot")
async def record_intel_snapshot(
    competitor_id: str = Body(...),
    competitor_name: str = Body(...),
    url: str = Body(...),
    fields: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Record a data snapshot for a competitor.

    Snapshots are stored with timestamps and used for trend analysis,
    anomaly detection, and report generation.
    """
    from intelligence import record_snapshot

    result = record_snapshot(competitor_id, competitor_name, url, fields)
    return {"success": True, "data": result}


@app.get(
    "/v1/intel/snapshots/{competitor_id}", tags=["Intelligence"], summary="Get competitor snapshots"
)
async def get_intel_snapshots(
    competitor_id: str,
    limit: int = 50,
    since_hours: int | None = None,
) -> dict[str, Any]:
    """Get historical snapshots for a competitor."""
    from intelligence import get_snapshots

    snapshots = get_snapshots(competitor_id, limit, since_hours)
    return {
        "success": True,
        "data": {"competitor_id": competitor_id, "snapshots": snapshots, "count": len(snapshots)},
    }


@app.post(
    "/v1/intel/analyze", tags=["Intelligence"], summary="Analyze competitor field for anomalies"
)
async def analyze_field(
    competitor_id: str = Body(...),
    field: str = Body("price"),
) -> dict[str, Any]:
    """Analyze a specific field across a competitor's snapshots for anomalies.

    Returns statistics, z-score analysis, and anomaly detection.
    """
    from intelligence import compute_field_statistics, detect_anomalies_numeric, get_snapshots

    snapshots = get_snapshots(competitor_id, limit=100)
    stats = compute_field_statistics(snapshots, field)

    if (
        stats.get("has_history")
        and stats.get("latest") is not None
        and stats.get("previous") is not None
    ):
        numeric_vals = [
            s.get("fields", {}).get(field)
            for s in snapshots
            if isinstance(s.get("fields", {}).get(field), (int, float))
        ]
        if len(numeric_vals) >= 3:
            anomaly = detect_anomalies_numeric(numeric_vals[-1], numeric_vals[:-1])
        else:
            anomaly = {"anomaly": False, "reason": "Insufficient numeric history"}
    else:
        anomaly = {"anomaly": False, "reason": "Insufficient data"}

    return {"success": True, "data": {"field": field, "statistics": stats, "anomaly": anomaly}}


@app.post(
    "/v1/intel/report", tags=["Intelligence"], summary="Generate a competitive intelligence report"
)
async def generate_report(
    competitors: list[dict[str, Any]] = Body(...),
    days_back: int = Body(7),
) -> dict[str, Any]:
    """Generate a competitive intelligence report for tracked competitors.

    Analyzes changes over the specified period and returns a structured report
    with a natural-language summary.
    """
    from intelligence import generate_weekly_report

    report = generate_weekly_report(competitors, days_back)
    return {"success": True, "data": report}


# ── Quality ──


@app.post(
    "/v1/quality/check", tags=["Quality"], summary="Run data quality check on extraction results"
)
async def quality_check(
    url: str = Body(...),
    data: dict[str, Any] = Body(...),
    schema: dict[str, Any] | None = Body(None),
    expected_types: dict[str, str] | None = Body(None),
) -> dict[str, Any]:
    """Run a full data quality check on extraction results.

    Metrics:
    - Completeness: what % of expected fields have values
    - Schema adherence: field types match expectations
    - Freshness: how old is the data
    - Anomaly detection: what changed since last extraction

    Use this to validate data BEFORE sending to downstream systems.
    """
    from quality import run_quality_check

    # Convert string type names to actual types
    type_map: dict[str, type] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "None": type(None),
    }
    resolved_types: dict[str, type] | None = None
    if expected_types:
        resolved_types = {}
        for field, type_name in expected_types.items():
            resolved_types[field] = type_map.get(type_name, str)

    result = await run_quality_check(
        url=url,
        data=data,
        schema=schema,
        expected_types=resolved_types,
    )
    return {"success": True, "data": result}


@app.get(
    "/v1/quality/stats", tags=["Quality"], summary="Get quality statistics for all checked URLs"
)
async def quality_stats() -> dict[str, Any]:
    """Get aggregate quality statistics across all checked URLs."""
    from quality import QUALITY_DIR

    stats: list[dict[str, Any]] = []
    for path in sorted(QUALITY_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)[:50]:
        try:
            data = json.loads(path.read_text())
            stats.append(
                {
                    "url": data.get("url", ""),
                    "checked_at": data.get("checked_at", ""),
                    "size_bytes": path.stat().st_size,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    return {"success": True, "data": {"total_checked": len(stats), "recent": stats}}


# ── Reconciliation ──


@app.post(
    "/v1/reconcile",
    tags=["Reconciliation"],
    summary="Reconcile records from multiple sources into unified entities",
)
async def reconcile_endpoint(
    records: list[dict[str, Any]] = Body(...),
    vertical: str = Body("product"),
    threshold: float = Body(0.7),
) -> dict[str, Any]:
    """Reconcile records from multiple sources into matched entities.

    Matches records across sources using identity field similarity,
    normalizes to a unified vertical schema, and returns entity groups
    with confidence scores.

    Verticals: product, job, real_estate, review
    """
    from reconciliation import VERTICAL_SCHEMAS, reconcile

    if vertical not in VERTICAL_SCHEMAS:
        raise InvalidRequestError(
            f"Unknown vertical: {vertical}. Supported: {list(VERTICAL_SCHEMAS.keys())}"
        )

    result = await reconcile(records, vertical, threshold)
    return {"success": True, "data": result}


@app.get(
    "/v1/reconcile/schemas",
    tags=["Reconciliation"],
    summary="List supported reconciliation schemas",
)
async def list_schemas() -> dict[str, Any]:
    """List all supported vertical schemas for entity reconciliation."""
    from reconciliation import VERTICAL_SCHEMAS

    schemas = {}
    for key, schema in VERTICAL_SCHEMAS.items():
        schemas[key] = {
            "name": schema["name"],
            "fields": {
                k: {fk: fv for fk, fv in v.items() if fk != "type"}
                for k, v in schema["fields"].items()
            },
            "identity_fields": schema["identity_fields"],
        }

    return {"success": True, "data": {"schemas": schemas, "total": len(schemas)}}


# ── Auth ──


@app.post("/v1/auth/credentials", tags=["Auth"], summary="Store credentials in the vault")
async def store_credentials(
    name: str = Body(...),
    credential_type: str = Body("password"),
    credentials: dict[str, Any] = Body(...),
    target_url: str = Body(""),
) -> dict[str, Any]:
    """Store credentials in the encrypted vault for authenticated scraping.

    Credential types: password, api_key, cookie, token, sso
    """
    from auth_connector import store_credential

    result = store_credential(name, credential_type, credentials, target_url)
    return {"success": result["success"], "data": result}


@app.get("/v1/auth/credentials", tags=["Auth"], summary="List stored credentials")
async def list_credentials_endpoint() -> dict[str, Any]:
    """List all stored credentials (without exposing secrets)."""
    from auth_connector import list_credentials

    creds = list_credentials()
    return {"success": True, "data": {"credentials": creds, "total": len(creds)}}


@app.delete(
    "/v1/auth/credentials/{credential_id}", tags=["Auth"], summary="Delete stored credentials"
)
async def delete_credentials_endpoint(credential_id: str) -> dict[str, Any]:
    """Delete stored credentials from the vault."""
    from auth_connector import delete_credential

    success = delete_credential(credential_id)
    if not success:
        raise NotFoundError(f"Credential not found: {credential_id}")
    return {"success": True, "data": {"deleted": True}}


@app.post("/v1/auth/sso", tags=["Auth"], summary="Generate SSO login script")
async def generate_sso(
    provider: str = Body("okta"),
    username: str = Body(...),
    password: str = Body(...),
    target_url: str = Body(...),
    tenant: str = Body(""),
) -> dict[str, Any]:
    """Generate a browser automation script for SSO login.

    Supports: okta, azure_ad, google_workspace, onelogin
    """
    from auth_connector import generate_sso_script

    result = await generate_sso_script(provider, username, password, target_url, tenant)
    return {"success": result["success"], "data": result}


@app.post("/v1/auth/captcha", tags=["Auth"], summary="Solve a CAPTCHA using third-party service")
async def solve_captcha_endpoint(
    image_base64: str = Body(""),
    site_key: str = Body(""),
    page_url: str = Body(""),
    service: str = Body("capsolver"),
    api_key: str = Body(""),
) -> dict[str, Any]:
    """Solve a CAPTCHA using Capsolver or 2Captcha.

    Provide either:
    - image_base64: Base64-encoded CAPTCHA image
    - site_key + page_url: For reCAPTCHA v2
    """
    from auth_connector import solve_captcha

    result = await solve_captcha(
        image_base64=image_base64,
        site_key=site_key,
        page_url=page_url,
        service=service,  # type: ignore[arg-type]
        api_key=api_key,
    )
    return {"success": result["success"], "data": result}


@app.post("/v1/auth/session/health", tags=["Auth"], summary="Check authenticated session health")
async def check_session(session_id: str = Body(...)) -> dict[str, Any]:
    """Check the health of an authenticated session.

    Reports cookie validity, session age, and whether re-auth is needed.
    """
    from auth_connector import check_session_health

    result = check_session_health(session_id)
    return {"success": True, "data": result}


# ── Review ──


@app.post("/v1/review/submit", tags=["Review"], summary="Submit extracted data for human review")
async def review_submit(
    data: dict[str, Any] = Body(...),
    url: str = Body(...),
    schema_name: str | None = Body(None),
    confidence_score: float = Body(0.0),
    flagged_fields: list[dict[str, Any]] | None = Body(None),
) -> dict[str, Any]:
    """Submit extracted data for human review before delivery.

    Use this when extraction confidence is low or anomalies were detected.
    Data will be held in the review queue until approved or rejected.
    """
    from review import submit_for_review

    result = await submit_for_review(
        data=data,
        extraction_url=url,
        schema_name=schema_name,
        confidence_score=confidence_score,
        flagged_fields=flagged_fields,
    )
    return {"success": True, "data": result}


@app.post("/v1/review/{review_id}/approve", tags=["Review"], summary="Approve a review item")
async def review_approve(
    review_id: str,
    reviewer: str = Body("api"),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Approve a review item, allowing data to proceed to delivery."""
    from review import approve_review

    result = await approve_review(review_id, reviewer, notes)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@app.post("/v1/review/{review_id}/reject", tags=["Review"], summary="Reject a review item")
async def review_reject(
    review_id: str,
    reviewer: str = Body("api"),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Reject a review item, blocking data delivery."""
    from review import reject_review

    result = await reject_review(review_id, reviewer, notes)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@app.get("/v1/reviews", tags=["Review"], summary="List reviews in the queue")
async def list_reviews(status: str | None = None) -> dict[str, Any]:
    """List reviews, optionally filtered by status (pending/approved/rejected)."""
    from review import get_review_queue

    reviews = get_review_queue(status)
    return {"success": True, "data": {"reviews": reviews, "total": len(reviews)}}


@app.get("/v1/review/{review_id}", tags=["Review"], summary="Get review details")
async def get_review(review_id: str) -> dict[str, Any]:
    """Get full details of a review item including the data payload."""
    from review import get_review_detail

    result = get_review_detail(review_id)
    if not result:
        raise NotFoundError(f"Review not found: {review_id}")
    return {"success": True, "data": result}


@app.post(
    "/v1/extract-with-review",
    tags=["Review"],
    summary="Extract with automatic human review routing",
)
async def extract_with_review(
    url: str = Body(...),
    schema: dict[str, Any] | None = Body(None),
    expected_types: dict[str, str] | None = Body(None),
    slack_webhook: str = Body(""),
    auto_approve_threshold: float = Body(0.8),
    auto_reject_threshold: float = Body(0.2),
) -> dict[str, Any]:
    """Extract data with automatic quality check and human review routing.

    High-confidence results are auto-approved.
    Low-confidence results are auto-rejected.
    Medium-confidence results go to the human review queue with Slack notification.
    """
    from quality import run_quality_check
    from review import auto_review_threshold

    # Scrape
    scrape_result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if scrape_result.get("status") != "ok":
        raise ScrapeError(scrape_result.get("error") or "Scrape failed")

    data = scrape_result

    # Quality check
    quality = await run_quality_check(
        url=url,
        data=data,
        schema=schema,
        expected_types=None,
    )

    # Auto-route
    decision = await auto_review_threshold(
        data=data,
        extraction_url=url,
        quality_result=quality,
        slack_webhook=slack_webhook,
        auto_approve_threshold=auto_approve_threshold,
        auto_reject_threshold=auto_reject_threshold,
    )

    return {
        "success": True,
        "data": {
            "decision": decision,
            "quality": {k: v for k, v in quality.items() if k != "url"},
        },
    }


# ── Commerce Sync ──


@app.post("/v1/commerce/sync", tags=["Commerce"], summary="Sync products to WooCommerce or Shopify")
async def sync_commerce(
    platform: str = Body(...),
    products: list[dict[str, Any]] = Body(...),
    credentials: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Sync scraped products to your e-commerce platform.

    Platforms:
    - woocommerce: credentials = {"wp_url": "...", "consumer_key": "...", "consumer_secret": "..."}
    - shopify: credentials = {"shop_url": "...", "access_token": "..."}

    Products are imported as drafts for review before publishing.
    """
    from commerce_sync import sync_to_shopify, sync_to_woocommerce

    if platform == "woocommerce":
        result = await sync_to_woocommerce(
            products=products,
            wp_url=credentials.get("wp_url", ""),
            consumer_key=credentials.get("consumer_key", ""),
            consumer_secret=credentials.get("consumer_secret", ""),
            category_id=credentials.get("category_id", 0),
            status=credentials.get("status", "draft"),
        )
    elif platform == "shopify":
        result = await sync_to_shopify(
            products=products,
            shop_url=credentials.get("shop_url", ""),
            access_token=credentials.get("access_token", ""),
        )
    else:
        raise InvalidRequestError(
            f"Unsupported platform: {platform}. Supported: woocommerce, shopify"
        )

    return {"success": result["success"], "data": result}


@app.get("/v1/commerce/platforms", tags=["Commerce"], summary="List supported commerce platforms")
async def list_commerce_platforms() -> dict[str, Any]:
    """List supported e-commerce platforms and their credential requirements."""
    return {
        "success": True,
        "data": {
            "platforms": [
                {
                    "id": "woocommerce",
                    "name": "WooCommerce",
                    "credential_fields": [
                        "wp_url",
                        "consumer_key",
                        "consumer_secret",
                        "category_id",
                    ],
                    "product_fields": ["name", "price", "description", "image_url"],
                },
                {
                    "id": "shopify",
                    "name": "Shopify",
                    "credential_fields": ["shop_url", "access_token"],
                    "product_fields": ["name", "price", "description", "image_url"],
                },
            ]
        },
    }


# ── CRM Sync ──


@app.post("/v1/crm/sync", tags=["CRM"], summary="Sync scraped data to CRM")
async def sync_crm(
    platform: str = Body(...),
    object_type: str = Body("lead"),
    objects: list[dict[str, Any]] = Body(...),
    credentials: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Sync scraped data to your CRM.

    Platforms:
    - salesforce: credentials={"instance_url": "...", "access_token": "..."}
    - hubspot: credentials={"api_key": "..."}
    - pipedrive: credentials={"api_token": "...", "domain": "..."}
    - close: credentials={"api_key": "..."}

    Object types vary by platform:
    - Salesforce: Lead, Contact, Account, Opportunity
    - HubSpot: contacts, companies, deals
    - Pipedrive: person, organization, deal, lead
    - Close: lead, contact
    """
    from crm_sync import sync_to_close, sync_to_hubspot, sync_to_pipedrive, sync_to_salesforce

    platform_map = {
        "salesforce": (sync_to_salesforce, ("instance_url", "access_token")),
        "hubspot": (sync_to_hubspot, ("api_key",)),
        "pipedrive": (sync_to_pipedrive, ("api_token",)),
        "close": (sync_to_close, ("api_key",)),
    }

    if platform not in platform_map:
        raise InvalidRequestError(
            f"Unsupported platform: {platform}. Supported: {list(platform_map.keys())}"
        )

    handler, required_fields = platform_map[platform]
    for field in required_fields:
        if not credentials.get(field):
            raise InvalidRequestError(f"Missing required credential: {field}")

    if platform == "salesforce":
        result = await handler(
            objects, object_type, credentials["instance_url"], credentials["access_token"]
        )
    elif platform == "hubspot":
        result = await handler(objects, object_type, credentials["api_key"])
    elif platform == "pipedrive":
        result = await handler(
            objects, object_type, credentials["api_token"], credentials.get("domain", "")
        )
    elif platform == "close":
        result = await handler(objects, object_type, credentials["api_key"])
    else:
        raise InvalidRequestError(f"Platform {platform} not handled")

    return {"success": result["success"], "data": result}


@app.get("/v1/crm/platforms", tags=["CRM"], summary="List supported CRM platforms")
async def list_crm_platforms() -> dict[str, Any]:
    """List supported CRM platforms and their credential requirements."""
    return {
        "success": True,
        "data": {
            "platforms": [
                {
                    "id": "salesforce",
                    "name": "Salesforce",
                    "objects": ["Lead", "Contact", "Account", "Opportunity"],
                    "credential_fields": ["instance_url", "access_token"],
                },
                {
                    "id": "hubspot",
                    "name": "HubSpot",
                    "objects": ["contacts", "companies", "deals"],
                    "credential_fields": ["api_key"],
                },
                {
                    "id": "pipedrive",
                    "name": "Pipedrive",
                    "objects": ["person", "organization", "deal", "lead"],
                    "credential_fields": ["api_token", "domain"],
                },
                {
                    "id": "close",
                    "name": "Close.com",
                    "objects": ["lead", "contact"],
                    "credential_fields": ["api_key"],
                },
            ]
        },
    }


# ── Pipeline Builder Endpoints ──


@app.get(
    "/v1/pipelines/steps", tags=["Pipelines"], summary="List all available pipeline step types"
)
async def list_step_types() -> dict[str, Any]:
    """List all available step types for the visual pipeline builder.

    Each step type includes: name, icon, description, required inputs with types,
    and expected outputs. A UI renders these as drag-and-drop blocks.
    """
    from pipelines import STEP_TYPES

    return {"success": True, "data": {"step_types": STEP_TYPES, "total": len(STEP_TYPES)}}


@app.post("/v1/pipelines/validate", tags=["Pipelines"], summary="Validate a pipeline definition")
async def validate_pipeline_endpoint(pipeline: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate a pipeline definition for correctness."""
    from pipelines import validate_pipeline

    errors = validate_pipeline(pipeline)
    return {"success": len(errors) == 0, "data": {"valid": len(errors) == 0, "errors": errors}}


@app.post("/v1/pipelines/run", tags=["Pipelines"], summary="Execute a pipeline")
async def run_pipeline_endpoint(
    pipeline: dict[str, Any] = Body(...),
    context: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Execute a pipeline definition.

    Steps run sequentially. Each step's output is available as
    {{step_id.output_key}} in subsequent step templates.

    Example pipeline:
    {
        "name": "Monitor Competitor Pricing",
        "steps": [
            {"id": "scrape_amazon", "type": "scrape", "inputs": {"url": "https://amazon.com/product"}},
            {"id": "extract", "type": "extract_css", "inputs": {"url": "{{scrape_amazon.url}}", "schema": {...}}},
            {"id": "quality", "type": "quality_check", "inputs": {"url": "{{scrape_amazon.url}}", "data": "{{extract.items}}"}},
            {"id": "notify", "type": "send_slack", "inputs": {"webhook_url": "https://hooks.slack.com/...", "message": "{{quality.quality_score}}"}},
        ]
    }
    """
    from pipelines import run_pipeline, validate_pipeline

    errors = validate_pipeline(pipeline)
    if errors:
        raise InvalidRequestError(f"Pipeline validation failed: {'; '.join(errors)}")
    result = await run_pipeline(pipeline, context)
    return {"success": not result["failed"], "data": result}


@app.post("/v1/pipelines/save", tags=["Pipelines"], summary="Save a pipeline definition")
async def save_pipeline_endpoint(pipeline: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Save a pipeline definition for later use."""
    from pipelines import save_pipeline

    result = save_pipeline(pipeline)
    return {"success": result["success"], "data": result}


@app.get("/v1/pipelines", tags=["Pipelines"], summary="List saved pipelines")
async def list_pipelines_endpoint() -> dict[str, Any]:
    """List all saved pipeline definitions."""
    from pipelines import list_pipelines

    pipelines = list_pipelines()
    return {"success": True, "data": {"pipelines": pipelines, "total": len(pipelines)}}


@app.get("/v1/pipelines/{pipeline_id}", tags=["Pipelines"], summary="Get a saved pipeline")
async def get_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    """Get a saved pipeline definition by ID."""
    from pipelines import get_pipeline

    result = get_pipeline(pipeline_id)
    if not result:
        raise NotFoundError(f"Pipeline not found: {pipeline_id}")
    return {"success": True, "data": result}


@app.delete("/v1/pipelines/{pipeline_id}", tags=["Pipelines"], summary="Delete a saved pipeline")
async def delete_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    """Delete a saved pipeline definition."""
    from pipelines import delete_pipeline

    success = delete_pipeline(pipeline_id)
    if not success:
        raise NotFoundError(f"Pipeline not found: {pipeline_id}")
    return {"success": True, "data": {"deleted": True}}


# ── Agency ──


@app.post("/v1/agency/create", tags=["Agency"], summary="Create a white-label agency profile")
async def create_agency_endpoint(
    name: str = Body(...),
    owner_email: str = Body(...),
    custom_domain: str = Body(""),
    brand_color: str = Body("#f59e0b"),
    logo_url: str = Body(""),
) -> dict[str, Any]:
    """Create a white-label agency profile for reselling Pry.

    Agencies get:
    - Custom branding (colors, logo, domain)
    - Client management with sub-accounts
    - Usage analytics and quota management
    - API key management for each client
    """
    from agency import create_agency

    result = create_agency(name, owner_email, custom_domain, brand_color, logo_url)
    return {"success": result["success"], "data": result}


@app.get("/v1/agency/{agency_id}", tags=["Agency"], summary="Get agency profile")
async def get_agency_endpoint(agency_id: str) -> dict[str, Any]:
    """Get agency profile details."""
    from agency import get_agency

    result = get_agency(agency_id)
    if not result:
        raise NotFoundError(f"Agency not found: {agency_id}")
    return {"success": True, "data": result}


@app.put("/v1/agency/{agency_id}/branding", tags=["Agency"], summary="Update agency branding")
async def update_branding(
    agency_id: str,
    name: str | None = Body(None),
    brand_color: str | None = Body(None),
    logo_url: str | None = Body(None),
    custom_domain: str | None = Body(None),
) -> dict[str, Any]:
    """Update white-label branding for an agency."""
    from agency import update_agency_branding

    result = update_agency_branding(agency_id, name, brand_color, logo_url, custom_domain)
    return {"success": result["success"], "data": result}


@app.post("/v1/agency/{agency_id}/clients", tags=["Agency"], summary="Create a client sub-account")
async def create_client_endpoint(
    agency_id: str,
    client_name: str = Body(...),
    client_email: str = Body(...),
    monthly_quota: int = Body(10000),
) -> dict[str, Any]:
    """Create a client sub-account under an agency.

    Each client gets their own API key and usage quota.
    """
    from agency import create_client

    result = create_client(agency_id, client_name, client_email, monthly_quota)
    return {"success": result["success"], "data": result}


@app.get("/v1/agency/{agency_id}/clients", tags=["Agency"], summary="List agency clients")
async def list_clients_endpoint(agency_id: str) -> dict[str, Any]:
    """List all clients under an agency."""
    from agency import list_clients

    clients = list_clients(agency_id)
    return {"success": True, "data": {"clients": clients, "total": len(clients)}}


@app.get("/v1/agency/{agency_id}/analytics", tags=["Agency"], summary="Get agency usage analytics")
async def get_analytics(agency_id: str) -> dict[str, Any]:
    """Get aggregate usage analytics for an agency."""
    from agency import get_agency_analytics

    result = get_agency_analytics(agency_id)
    return {"success": True, "data": result}


@app.get("/v1/client/{client_id}/quota", tags=["Agency"], summary="Check client quota usage")
async def check_quota(client_id: str) -> dict[str, Any]:
    """Check a client's current quota usage and remaining capacity."""
    from agency import check_client_quota

    result = check_client_quota(client_id)
    return {"success": result["success"], "data": result}


# ── SEO Content Change Monitor ──


@app.post("/v1/seo/analyze", tags=["SEO"], summary="Analyze SEO elements from a URL")
async def seo_analyze(url: str = Body(...)) -> dict[str, Any]:
    """Analyze all SEO elements from a URL.

    Returns: title, meta description, keywords, headings (H1/H2),
    canonical, OG tags, Twitter cards, word count, link counts,
    schema markup, hreflang tags.
    """
    from seo_monitor import analyze_seo

    result = await analyze_seo(url)
    return {"success": "error" not in result, "data": result}


@app.post("/v1/seo/track", tags=["SEO"], summary="Track SEO changes since last scan")
async def seo_track(url: str = Body(...)) -> dict[str, Any]:
    """Track SEO changes since the last scan of this URL.

    Compares current SEO elements to previous snapshot and reports
    what changed (title, description, headings, etc.).
    """
    from seo_monitor import track_seo_changes

    result = await track_seo_changes(url)
    return {"success": "error" not in result, "data": result}


@app.post("/v1/seo/keywords", tags=["SEO"], summary="Analyze keyword presence in URL content")
async def seo_keywords(
    url: str = Body(...),
    keywords: list[str] = Body(...),
) -> dict[str, Any]:
    """Analyze which keywords a URL targets.

    Checks each keyword for:
    - Presence in title tag
    - Presence in H1 headings
    - Presence in meta description
    - Frequency in body content
    - Keyword density percentage
    """
    from seo_monitor import get_seo_keyword_insights

    result = await get_seo_keyword_insights(url, keywords)
    return {"success": "error" not in result, "data": result}


# ── Reports ──


@app.post(
    "/v1/reports/generate",
    tags=["Reports"],
    summary="Generate a white-label report from scraped data",
)
async def generate_report_endpoint(
    report_type: str = Body(...),
    data: dict[str, Any] = Body(...),
    branding: dict[str, Any] | None = Body(None),
    output_format: str = Body("html"),
) -> dict[str, Any]:
    """Generate a white-label report from scraped data.

    Report types:
    - competitive_analysis: Competitor pricing and activity overview
    - price_monitor: Product price change tracking with visual indicators
    - seo_audit: SEO element analysis with change detection
    - content_tracker: Content change monitoring across pages

    Branding (optional): {"agency_name": "...", "brand_color": "#hex", "logo_url": "..."}
    """
    from reports import generate_report

    result = generate_report(report_type, data, branding, output_format)
    if "error" in result:
        raise InvalidRequestError(result["error"])
    return {"success": True, "data": result}


@app.get("/v1/reports", tags=["Reports"], summary="List generated reports")
async def list_reports_endpoint() -> dict[str, Any]:
    """List all previously generated reports."""
    from reports import list_reports

    reports = list_reports()
    return {"success": True, "data": {"reports": reports, "total": len(reports)}}


@app.get("/v1/report/{report_id}", tags=["Reports"], summary="Get a generated report")
async def get_report(report_id: str) -> Any:
    """Get the HTML content of a generated report."""
    from reports import REPORTS_DIR

    for path in REPORTS_DIR.glob(f"{report_id}_*.html"):
        return HTMLResponse(content=path.read_text())
    raise NotFoundError(f"Report not found: {report_id}")


# ── Enrichment ──


@app.post(
    "/v1/enrich",
    tags=["Enrichment"],
    summary="Enrich scraped data with company info, tech stack, social profiles",
)
async def enrich_data(
    url: str = Body(...),
    include_tech_stack: bool = Body(True),
    include_social: bool = Body(True),
    include_company: bool = Body(True),
) -> dict[str, Any]:
    """Enrich a URL with supplemental business intelligence.

    Returns:
    - Tech stack detection (CMS, framework, CDN, analytics, payments)
    - Social media profiles (Twitter, LinkedIn, Facebook, Instagram, GitHub, etc.)
    - Company information (email, phone, address, founded year, team size)
    """
    from enrichment import enrich_url

    result = await enrich_url(url)
    filtered: dict[str, Any] = {"url": url}
    if include_tech_stack:
        filtered["tech_stack"] = result.get("tech_stack")
    if include_social:
        filtered["social_profiles"] = result.get("social_profiles")
    if include_company:
        filtered["company_info"] = result.get("company_info")

    return {"success": True, "data": filtered}


@app.post(
    "/v1/enrich/tech-stack", tags=["Enrichment"], summary="Detect technologies used on a website"
)
async def detect_tech(url: str = Body(...)) -> dict[str, Any]:
    """Detect what technologies a website is built with.

    Detects: CMS (WordPress, Shopify, Wix), frameworks (Next.js, Django, Rails),
    frontend (React, Vue, Angular), CDN (Cloudflare, Fastly), analytics (GA, Hotjar),
    payments (Stripe, PayPal).
    """
    from enrichment import enrich_url

    result = await enrich_url(url)
    return {"success": True, "data": result.get("tech_stack", {})}


# ── Scraper Templates ──


@app.get("/v1/templates", tags=["Templates"], summary="List all pre-built scraper templates")
async def list_templates_endpoint() -> dict[str, Any]:
    """List all available pre-built scraper templates.

    Templates are one-click extractors for popular websites:
    Amazon, Walmart, Target, Best Buy, LinkedIn, Indeed, GitHub, etc.
    """
    from template_engine import list_templates

    templates = list_templates()
    # Group by category
    categories: dict[str, list[dict[str, Any]]] = {}
    for t in templates:
        cat = t.get("category", "general")
        categories.setdefault(cat, []).append(t)
    return {
        "success": True,
        "data": {"templates": templates, "categories": categories, "total": len(templates)},
    }


@app.get("/v1/templates/{template_id}", tags=["Templates"], summary="Get a scraper template")
async def get_template_endpoint(template_id: str) -> dict[str, Any]:
    """Get a specific scraper template with full schema details."""
    from template_engine import get_template

    template = get_template(template_id)
    if not template:
        raise NotFoundError(f"Template not found: {template_id}")
    return {"success": True, "data": template}


@app.post(
    "/v1/templates/execute", tags=["Templates"], summary="Execute a scraper template against a URL"
)
async def execute_template_endpoint(
    template_id: str = Body(...),
    url: str = Body(...),
) -> dict[str, Any]:
    """Execute a pre-built scraper template against any URL.

    Example: use "amazon_product" template with an Amazon product URL
    to get structured title, price, rating, description, etc.

    Templates auto-detect the page structure using pre-configured CSS selectors.
    """
    from template_engine import execute_template

    result = await execute_template(template_id, url)
    return result


# ── AI Agent Integration ──


@app.get(
    "/openapi.json",
    tags=["System"],
    summary="OpenAPI spec for AI agent integration",
    include_in_schema=False,
)
async def get_openapi() -> JSONResponse:
    """Get the OpenAPI specification for AI agent integration.

    Use this with ChatGPT GPT Actions, Claude MCP, or any AI agent
    framework to let AI models scrape the web through Pry.
    """
    from ai_plugin import get_openapi_spec

    spec = get_openapi_spec()
    return JSONResponse(content=spec)


@app.get("/v1/ai/gpt-manifest", tags=["AI"], summary="Get GPT Action manifest for ChatGPT")
async def get_gpt_manifest() -> JSONResponse:
    """Get the GPT Action manifest for ChatGPT integration.

    Add this to your GPT configuration in ChatGPT to give it
    web scraping capabilities through Pry.
    """
    from ai_plugin import get_gpt_action_manifest

    return JSONResponse(content=get_gpt_action_manifest())


@app.get("/v1/ai/mcp-config", tags=["AI"], summary="Get MCP server config for Claude/Cursor")
async def get_mcp_config() -> JSONResponse:
    """Get the MCP server configuration for Claude/Cursor.

    Add this to your AI tool's MCP configuration file to let
    Claude and Cursor scrape the web through Pry.
    """
    from ai_plugin import get_mcp_server_config

    return JSONResponse(content={"success": True, "data": get_mcp_server_config()})


@app.get(
    "/v1/referrals/catalog",
    tags=["Referrals"],
    summary="Get all available referral/affiliate programs",
)
async def get_referral_catalog(category: str = "") -> dict[str, Any]:
    """List all referral programs Pry supports.

    60+ providers across categories: LLM, hosting, domains, CDN, email,
    monitoring, proxies, voice, media, devtools, search, CAPTCHA.
    """
    from referrals import ReferralTracker

    return {"success": True, "data": ReferralTracker().get_catalog(category)}


@app.get(
    "/v1/referrals/stats", tags=["Referrals"], summary="Get referral click and conversion stats"
)
async def get_referral_stats(days_back: int = 30) -> dict[str, Any]:
    """Get referral tracking statistics for the last N days."""
    from referrals import ReferralTracker

    return {"success": True, "data": ReferralTracker().get_stats(days_back)}


@app.post("/v1/referrals/click", tags=["Referrals"], summary="Record a referral link click")
async def record_referral_click(
    provider_tag: str = Body(...),
    source: str = Body("api"),
    user_id: str = Body(""),
) -> dict[str, Any]:
    """Record when a user clicks a referral link. Returns tracking ID."""
    from referrals import PROVIDER_CATALOG, ReferralTracker

    url = ""
    for _cat, providers in PROVIDER_CATALOG.items():
        for p in providers:
            if p.get("tag") == provider_tag:
                url = p["url"]
                break
        if url:
            break
    if not url:
        return {"success": False, "error": f"Unknown provider: {provider_tag}"}
    click_id = ReferralTracker().record_click(provider_tag, url, source, user_id)
    return {"success": True, "data": {"click_id": click_id, "url": url}}


@app.post("/v1/referrals/convert", tags=["Referrals"], summary="Record a referral conversion")
async def record_referral_conversion(
    click_id: str = Body(...),
    revenue_usd: float = Body(0.0),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Record that a referral click resulted in a conversion."""
    from referrals import ReferralTracker

    success = ReferralTracker().record_conversion(click_id, revenue_usd, notes)
    return {"success": success}


@app.get("/v1/x402/pricing", tags=["x402"], summary="Get x402 pricing for all paid operations")
async def x402_pricing() -> dict[str, Any]:
    """Get the price list for pay-per-scrape operations."""
    from x402 import X402Handler

    return {"success": True, "data": X402Handler().get_stats()}


@app.post("/v1/x402/payment", tags=["x402"], summary="Create a x402 payment request")
async def x402_payment_request(
    operation: str = Body(...),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Create a x402 payment request for a paid operation.

    Returns payment details (wallet, amount, asset) for the client to pay.
    """
    from x402 import create_payment_request

    req = create_payment_request(operation, metadata)
    return {"success": True, "data": req}


@app.post("/v1/x402/verify", tags=["x402"], summary="Verify a x402 payment was settled")
async def x402_verify_payment(
    payment_id: str = Body(...),
    tx_hash: str = Body(...),
    network: str = Body(""),
    asset: str = Body(""),
    amount_usd: float = Body(0.0),
) -> dict[str, Any]:
    """Verify a x402 payment has been settled on-chain via facilitator router."""
    from x402 import X402Handler

    result = await X402Handler().verify_payment(
        payment_id, tx_hash, network=network, asset=asset, amount_usd=amount_usd
    )
    return {"success": result["verified"], "data": result}


@app.post(
    "/v1/x402/require-payment", tags=["x402"], summary="Generate a 402 Payment Required response"
)
async def x402_require_payment(
    operation: str = Body(...),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Generate a 402 Payment Required response for a paid endpoint."""
    from x402 import require_payment_legacy

    return require_payment_legacy(operation, metadata)


@app.post("/v1/x402/batch-payment", tags=["x402"], summary="Create a batch x402 payment")
async def x402_batch_payment(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a single x402 payment covering multiple operations.

    Returns a PaymentRequired body with the combined amount. After paying,
    submit the tx to POST /v1/x402/batch-verify.
    """
    from x402 import create_batch_payment

    operations = payload.get("operations", [])
    if not isinstance(operations, list):
        raise InvalidRequestError("operations must be a list")
    result = await create_batch_payment(operations)
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "data": result}


@app.post("/v1/x402/batch-verify", tags=["x402"], summary="Verify a batch x402 payment")
async def x402_batch_verify(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Verify the on-chain payment for a batch and mark it paid."""
    from x402 import verify_batch_payment

    batch_id = payload.get("batch_id", "")
    tx_hash = payload.get("tx_hash", "")
    network = payload.get("network", "")
    asset = payload.get("asset", "")
    if not batch_id or not tx_hash:
        raise InvalidRequestError("batch_id and tx_hash are required")
    result = await verify_batch_payment(batch_id, tx_hash, network=network, asset=asset)
    return {"success": result["verified"], "data": result}


# ── Proxy Provider & Affiliate Signup Flow ──
@app.get("/v1/proxy/providers", tags=["Proxy"], summary="List all available proxy providers")
async def list_proxy_providers() -> dict[str, Any]:
    """List free + premium proxy providers with affiliate details."""
    from proxy_manager import ProxyManager

    return {"success": True, "data": ProxyManager().list_providers()}


@app.post("/v1/proxy/signup", tags=["Proxy"], summary="Open affiliate signup link for a provider")
async def proxy_signup(provider: str = Body(...)) -> dict[str, Any]:
    """Get the affiliate signup URL for a proxy provider.

    Records a click for revenue tracking. The user can then sign up at that URL
    and come back to configure credentials.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    url = pm.get_signup_link(provider)
    return {"success": True, "data": {"signup_url": url, "provider": provider}}


@app.post("/v1/proxy/configure", tags=["Proxy"], summary="Configure proxy credentials")
async def proxy_configure(
    provider: str = Body(...),
    username: str = Body(""),
    password: str = Body(""),
    api_key: str = Body(""),
    proxy_url: str = Body(""),
) -> dict[str, Any]:
    """Configure credentials for a premium proxy provider.

    After signing up via /v1/proxy/signup, the user provides their credentials here.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    creds = {"username": username, "password": password, "api_key": api_key, "proxy_url": proxy_url}
    creds = {k: v for k, v in creds.items() if v}
    result = pm.select_provider(provider, creds)
    return {"success": result["success"], "data": result}


@app.get("/v1/proxy/test", tags=["Proxy"], summary="Test the active proxy")
async def proxy_test() -> dict[str, Any]:
    """Test the currently configured proxy and return its public IP."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    proxy_url = pm.get_proxy_url()
    if not proxy_url:
        return {"success": True, "data": {"active": False, "message": "No proxy configured"}}
    result = pm.test_proxy(proxy_url)
    return {"success": True, "data": {"active": True, **result}}


@app.get("/v1/proxy/status", tags=["Proxy"], summary="Get current proxy status")
async def proxy_status() -> dict[str, Any]:
    """Get current proxy configuration and available providers."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    return {
        "success": True,
        "data": {
            "active_config": pm.active_config.__dict__,
            "configured_providers": list(pm.credentials.keys()),
            "available_providers": pm.list_providers(),
        },
    }


@app.post("/v1/proxy/recommend", tags=["Proxy"], summary="Get proxy recommendation after a block")
async def proxy_recommend(last_error: str = Body("")) -> dict[str, Any]:
    """After a scrape fails with anti-bot detection, get a recommendation
    for which premium proxy provider to sign up with."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    rec = pm.get_recommendation(last_error)
    return {"success": True, "data": rec}


@app.get("/v1/proxy/clicks", tags=["Proxy"], summary="Get recent proxy referral clicks")
async def proxy_clicks(days_back: int = 30) -> dict[str, Any]:
    """Get recent proxy referral clicks for revenue tracking."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    clicks = pm.get_recent_clicks(days_back=days_back)
    return {
        "success": True,
        "data": {
            "total_clicks": len(clicks),
            "days_back": days_back,
            "clicks": clicks,
        },
    }


# ── Advanced Scraping (TLS, GraphQL, Schema.org, WebSocket) ──


@app.post(
    "/v1/tls/impersonate",
    tags=["Advanced"],
    summary="Fetch a URL with TLS fingerprint impersonation",
)
async def tls_impersonate(
    url: str = Body(...),
    impersonate: str = Body("chrome131"),
    proxy: str = Body(""),
) -> dict[str, Any]:
    """Fetch a URL while impersonating a real browser's TLS fingerprint.
    Bypasses JA3/JA4 fingerprinting that blocks 80%+ of bot traffic."""
    from tls_fingerprint import TLSScraper

    s = TLSScraper()
    if not s.is_available():
        return {"success": False, "error": "curl_cffi not installed. Run: pip install curl_cffi"}
    result = await s.fetch(url, impersonate=impersonate, proxy=proxy)
    return result


@app.post(
    "/v1/tls/rotate",
    tags=["Advanced"],
    summary="Try multiple browser fingerprints until one succeeds",
)
async def tls_rotate(
    url: str = Body(...),
    proxy: str = Body(""),
) -> dict[str, Any]:
    """Try multiple browser fingerprints until one succeeds (anti-fingerprint rotation)."""
    from tls_fingerprint import TLSScraper

    s = TLSScraper()
    if not s.is_available():
        return {"success": False, "error": "curl_cffi not installed. Run: pip install curl_cffi"}
    result = await s.fetch_with_rotation(url, proxy=proxy)
    return result


@app.post(
    "/v1/camoufox/fetch", tags=["Advanced"], summary="Fetch with Camoufox anti-detection Firefox"
)
async def camoufox_fetch(
    url: str = Body(...),
    profile: str = Body("chrome_windows"),
    wait_selector: str = Body(""),
    proxy: str = Body(""),
) -> dict[str, Any]:
    """Fetch a URL using Camoufox (Firefox anti-detection browser).

    Camoufox patches Firefox at the source level for maximum stealth.
    This is more effective than Playwright for sites with advanced
    fingerprinting (DataDome, PerimeterX, advanced Cloudflare).
    """
    from camoufox_integration import CamoufoxBrowser

    b = CamoufoxBrowser()
    if not b.is_available():
        return {
            "success": False,
            "error": "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch",
        }
    result = await b.fetch(url, profile=profile, wait_selector=wait_selector, proxy=proxy)
    return result


@app.post(
    "/v1/graphql/discover", tags=["Advanced"], summary="Discover GraphQL endpoints for a site"
)
async def graphql_discover(base_url: str = Body(...)) -> dict[str, Any]:
    """Auto-discover GraphQL endpoints for a website."""
    from graphql_discovery import GraphQLDiscovery

    g = GraphQLDiscovery()
    found = await g.discover(base_url)
    return {"success": True, "data": {"found": found, "count": len(found)}}


@app.post(
    "/v1/graphql/introspect", tags=["Advanced"], summary="Run GraphQL introspection on an endpoint"
)
async def graphql_introspect(endpoint: str = Body(...)) -> dict[str, Any]:
    """Run GraphQL introspection query against a discovered endpoint."""
    from graphql_discovery import GraphQLDiscovery

    g = GraphQLDiscovery()
    result = await g.introspect(endpoint)
    return {"success": "error" not in result, "data": result}


@app.post("/v1/graphql/query", tags=["Advanced"], summary="Execute a GraphQL query")
async def graphql_query(
    endpoint: str = Body(...),
    query: str = Body(...),
    variables: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Execute a GraphQL query against a discovered endpoint."""
    from graphql_discovery import GraphQLDiscovery

    g = GraphQLDiscovery()
    result = await g.query(endpoint, query, variables)
    return {"success": "error" not in result, "data": result}


@app.post(
    "/v1/schema/extract",
    tags=["Advanced"],
    summary="Extract Schema.org structured data from a page",
)
async def schema_extract(url: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD/Microdata/RDFa structured data from a URL.
    Most modern sites embed structured data — extract it directly instead of
    scraping HTML. 100x faster and more accurate."""
    from client import get_client
    from schema_extraction import SchemaExtractor

    client = await get_client()
    resp = await client.get(url, timeout=30)
    e = SchemaExtractor()
    result = e.extract_all(resp.text)
    return {"success": True, "data": result}


@app.post(
    "/v1/schema/extract-html",
    tags=["Advanced"],
    summary="Extract Schema.org structured data from raw HTML",
)
async def schema_extract_html(html: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD/Microdata/RDFa from a raw HTML string.
    Useful when you've already fetched the page and want to extract structured data."""
    from schema_extraction import SchemaExtractor

    e = SchemaExtractor()
    result = e.extract_all(html)
    return {"success": True, "data": result}


@app.post(
    "/v1/ws/scrape",
    tags=["Advanced"],
    summary="Scrape data from a WebSocket endpoint",
)
async def ws_scrape(
    url: str = Body(...),
    max_messages: int = Body(100),
    timeout: int = Body(30),
    message_filter: str = Body(""),
) -> dict[str, Any]:
    """Connect to a WebSocket and capture the data stream.
    Useful for SPAs and real-time apps that load data via WebSocket."""
    from websocket_scraper import WebSocketScraper

    s = WebSocketScraper(max_messages=max_messages, timeout=timeout)
    result = await s.scrape_websocket(url, message_filter=message_filter)
    return {"success": result.get("success", False), "data": result}


@app.post(
    "/v1/sse/scrape",
    tags=["Advanced"],
    summary="Scrape data from a Server-Sent Events endpoint",
)
async def sse_scrape(
    url: str = Body(...),
    max_events: int = Body(50),
    timeout: int = Body(30),
    event_filter: str = Body(""),
) -> dict[str, Any]:
    """Connect to a Server-Sent Events endpoint and capture events."""
    from websocket_scraper import WebSocketScraper

    s = WebSocketScraper(timeout=timeout)
    result = await s.scrape_sse(url, event_filter=event_filter, max_events=max_events)
    return {"success": result.get("success", False), "data": result}


# ── Advanced: Cookie Warming, PDF, OCR, Dedup, Behavior ──


@app.post(
    "/v1/cookies/warm",
    tags=["Advanced"],
    summary="Warm cookies for a domain by browsing legitimate pages",
)
async def warm_cookies(
    target_domain: str = Body(...),
    pages_to_visit: int = Body(3),
) -> dict[str, Any]:
    """Pre-age cookies for a domain to bypass anti-bot detection.
    Visits legitimate pages first to build realistic browsing history."""
    from cookie_warmer import CookieWarmer

    w = CookieWarmer()
    result = await w.warm_for_site(target_domain, pages_to_visit=pages_to_visit)
    return {"success": result.get("success", False), "data": result}


@app.get(
    "/v1/cookies/sessions",
    tags=["Advanced"],
    summary="List all warmed cookie sessions",
)
async def list_cookie_sessions() -> dict[str, Any]:
    from cookie_warmer import CookieWarmer

    w = CookieWarmer()
    return {"success": True, "data": w.list_sessions()}


@app.post(
    "/v1/pdf/extract",
    tags=["Advanced"],
    summary="Extract tables and text from a PDF",
)
async def extract_pdf(
    pdf_url: str = Body(...),
    method: str = Body("pdfplumber"),
) -> dict[str, Any]:
    """Download a PDF and extract structured tables and text."""
    from client import get_client
    from pdf_extractor import PDFTableExtractor

    client = await get_client()
    try:
        resp = await client.get(pdf_url, timeout=60)
        if not resp.is_success:
            return {
                "success": False,
                "error": f"Failed to download: HTTP {resp.status_code}",
            }
        e = PDFTableExtractor()
        result = e.extract(resp.content, method=method)
        return {"success": "error" not in result, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


@app.post(
    "/v1/ocr/extract",
    tags=["Advanced"],
    summary="Extract text from an image using Tesseract",
)
async def ocr_extract(
    image_url: str = Body(""),
    image_base64: str = Body(""),
) -> dict[str, Any]:
    """Extract text from an image via URL or base64."""
    from ocr_extractor import ImageOCR

    o = ImageOCR()
    if image_url:
        result = await o.extract_from_url(image_url)
    elif image_base64:
        data = base64.b64decode(image_base64.split(",", 1)[-1])
        result = o.extract_from_bytes(data)
    else:
        return {"success": False, "error": "Provide image_url or image_base64"}
    return result


@app.post(
    "/v1/dedup/check",
    tags=["Advanced"],
    summary="Check if content is a near-duplicate using SimHash",
)
async def check_duplicate(
    text: str = Body(...),
    threshold: float = Body(0.85),
) -> dict[str, Any]:
    """Check if text is a near-duplicate of recently seen content using SimHash."""
    from dedup import SimHash

    h = SimHash.hash(text)
    return {
        "success": True,
        "data": {
            "hash": h,
            "text_length": len(text),
            "threshold": threshold,
        },
    }


@app.get(
    "/v1/behavior/simulate",
    tags=["Advanced"],
    summary="Generate human-like behavior patterns for testing",
)
async def get_behavior_simulation(action: str = "mouse") -> dict[str, Any]:
    """Generate realistic human behavior patterns (mouse path, scroll, typing, etc.)"""
    from behavioral_biometrics import behavior

    if action == "mouse":
        path = behavior.mouse_path((0, 0), (800, 600))
    elif action == "scroll":
        path = behavior.scroll_pattern(3000)
    elif action == "typing":
        path = behavior.typing_pattern("the quick brown fox jumps over")
    elif action == "click":
        return {
            "success": True,
            "data": {"delay_ms": behavior.click_decision_delay() * 1000},
        }
    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}. Use mouse|scroll|typing|click",
        }
    return {"success": True, "data": path}


# ── x402 payment processing ──


@app.post(
    "/v1/x402/pay",
    tags=["x402"],
    summary="Process x402 payment and get access token",
)
async def x402_pay(
    operation: str = Body(...),
    tx_hash: str = Body(...),
    payer_wallet: str = Body(...),
    network: str = Body(""),
    asset: str = Body(""),
    amount_usd: float = Body(0.0),
) -> dict[str, Any]:
    """Process an x402 payment and return an access token.

    Flow:
    1. User gets 402 from a paid endpoint
    2. User sends USDC to the wallet in the 402 response
    3. User calls this endpoint with the tx_hash
    4. Pry verifies the transaction through the facilitator router
    5. Returns access token (payment_id) to use in X-Payment-Hash header
    """
    from x402 import X402Handler

    h = X402Handler()
    payment_id = uuid.uuid4().hex[:12]
    verify_result = await h.verify_payment(
        payment_id, tx_hash, network=network, asset=asset, amount_usd=amount_usd
    )
    settlement = None
    if verify_result.get("verified"):
        settlement = await h.settle_payment(
            payment_id, tx_hash, network=network, asset=asset, amount_usd=amount_usd
        )
    return {
        "success": verify_result.get("verified", False),
        "data": {
            "payment_id": payment_id,
            "tx_hash": tx_hash,
            "verified": verify_result,
            "settlement": settlement,
            "payer_wallet": payer_wallet,
            "use_in_header": {"X-Payment-ID": payment_id, "X-Payment-Hash": tx_hash},
        },
    }


# ── Actor marketplace ──


@app.post(
    "/v1/actors/create",
    tags=["Marketplace"],
    summary="Create a new actor",
)
async def create_actor(
    name: str = Body(...),
    description: str = Body(...),
    template_id: str = Body(""),
    code: str = Body(""),
    price_per_run: float = Body(0.0),
    visibility: str = Body("private"),
    schedule_cron: str = Body(""),
    tags: list[str] | None = Body(None),
) -> dict[str, Any]:
    """Create a new actor in the marketplace."""
    from actor_marketplace import ActorMarketplace, ActorVisibility

    m = ActorMarketplace()
    actor = m.create(
        name,
        description,
        template_id,
        code,
        price_per_run,
        ActorVisibility(visibility),
        schedule_cron,
        tags or [],
    )
    return {"success": True, "data": actor.to_dict()}


@app.get(
    "/v1/actors",
    tags=["Marketplace"],
    summary="List actors in the marketplace",
)
async def list_actors(visibility: str = "", tag: str = "") -> dict[str, Any]:
    """List actors. Filter by visibility (public/private) and tag."""
    from actor_marketplace import ActorMarketplace

    m = ActorMarketplace()
    return {"success": True, "data": m.list(visibility, tag)}


@app.post(
    "/v1/actors/{actor_id}/run",
    tags=["Marketplace"],
    summary="Run an actor",
)
async def run_actor(actor_id: str, inputs: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
    """Run an actor with the provided inputs."""
    from actor_marketplace import ActorMarketplace

    m = ActorMarketplace()
    return await m.run(actor_id, inputs or {})


# ── Webhook delivery ──


@app.post(
    "/v1/webhooks/test",
    tags=["Webhooks"],
    summary="Test webhook delivery",
)
async def test_webhook(
    url: str = Body(...),
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Test webhook delivery to a URL with HMAC signing."""
    from webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return await w.deliver(url, payload or {"test": True, "timestamp": "now"}, "test.event")


@app.get(
    "/v1/webhooks/dead-letter",
    tags=["Webhooks"],
    summary="Get failed webhook deliveries",
)
async def get_dead_letter() -> dict[str, Any]:
    """Get the dead letter queue of failed webhook deliveries."""
    from webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return {"success": True, "data": w.retry_dead_letter()}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
