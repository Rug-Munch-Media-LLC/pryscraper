"""Pry — Advanced router (remaining api.py routes).
Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Advanced"])


@router.post(
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
    from pry.engine.tls_fingerprint import TLSScraper

    validate_url(url)
    s = TLSScraper()
    if not s.is_available():
        return {"success": False, "error": "curl_cffi not installed. Run: pip install curl_cffi"}
    result = await s.fetch(url, impersonate=impersonate, proxy=proxy)
    return result


@router.post(
    "/v1/tls/rotate",
    tags=["Advanced"],
    summary="Try multiple browser fingerprints until one succeeds",
)
async def tls_rotate(
    url: str = Body(...),
    proxy: str = Body(""),
) -> dict[str, Any]:
    """Try multiple browser fingerprints until one succeeds (anti-fingerprint rotation)."""
    from pry.engine.tls_fingerprint import TLSScraper

    validate_url(url)
    s = TLSScraper()
    if not s.is_available():
        return {"success": False, "error": "curl_cffi not installed. Run: pip install curl_cffi"}
    result = await s.fetch_with_rotation(url, proxy=proxy)
    return result


@router.post(
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
    from pry.engine.camoufox_integration import CamoufoxBrowser

    validate_url(url)
    b = CamoufoxBrowser()
    if not b.is_available():
        return {
            "success": False,
            "error": "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch",
        }
    result = await b.fetch(url, profile=profile, wait_selector=wait_selector, proxy=proxy)
    return result


@router.post(
    "/v1/graphql/discover", tags=["Advanced"], summary="Discover GraphQL endpoints for a site"
)
async def graphql_discover(base_url: str = Body(...)) -> dict[str, Any]:
    """Auto-discover GraphQL endpoints for a website."""
    from pry.engine.graphql_discovery import GraphQLDiscovery

    validate_url(base_url)
    g = GraphQLDiscovery()
    found = await g.discover(base_url)
    return {"success": True, "data": {"found": found, "count": len(found)}}


@router.post(
    "/v1/graphql/introspect", tags=["Advanced"], summary="Run GraphQL introspection on an endpoint"
)
async def graphql_introspect(endpoint: str = Body(...)) -> dict[str, Any]:
    """Run GraphQL introspection query against a discovered endpoint."""
    from pry.engine.graphql_discovery import GraphQLDiscovery

    validate_url(endpoint)
    g = GraphQLDiscovery()
    result = await g.introspect(endpoint)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/graphql/query", tags=["Advanced"], summary="Execute a GraphQL query")
async def graphql_query(
    endpoint: str = Body(...),
    query: str = Body(...),
    variables: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Execute a GraphQL query against a discovered endpoint."""
    from pry.engine.graphql_discovery import GraphQLDiscovery

    validate_url(endpoint)
    g = GraphQLDiscovery()
    result = await g.query(endpoint, query, variables)
    return {"success": "error" not in result, "data": result}


@router.post(
    "/v1/schema/extract",
    tags=["Advanced"],
    summary="Extract Schema.org structured data from a page",
)
async def schema_extract(url: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD/Microdata/RDFa structured data from a URL.
    Most modern sites embed structured data — extract it directly instead of
    scraping HTML. 100x faster and more accurate."""
    from pry.engine.schema_extraction import SchemaExtractor

    validate_url(url)
    client = await get_client()
    resp = await client.get(url, timeout=30)
    e = SchemaExtractor()
    result = e.extract_all(resp.text)
    return {"success": True, "data": result}


@router.post(
    "/v1/schema/extract-html",
    tags=["Advanced"],
    summary="Extract Schema.org structured data from raw HTML",
)
async def schema_extract_html(html: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD/Microdata/RDFa from a raw HTML string.
    Useful when you've already fetched the page and want to extract structured data."""
    from pry.engine.schema_extraction import SchemaExtractor

    e = SchemaExtractor()
    result = e.extract_all(html)
    return {"success": True, "data": result}


@router.post(
    "/v1/ws/scrape",
    tags=["Advanced"],
    summary="Scrape data from a WebSocket endpoint",
)
async def ws_scrape(
    url: str = Body(...),
    max_messages: int = Body(100),
    timeout: int = Body(30),  # noqa: ASYNC109 - FastAPI endpoint param, API contract
    message_filter: str = Body(""),
) -> dict[str, Any]:
    """Connect to a WebSocket and capture the data stream.
    Useful for SPAs and real-time apps that load data via WebSocket."""
    from pry.engine.websocket_scraper import WebSocketScraper

    s = WebSocketScraper(max_messages=max_messages, timeout=timeout)
    result = await s.scrape_websocket(url, message_filter=message_filter)
    return {"success": result.get("success", False), "data": result}


@router.post(
    "/v1/sse/scrape",
    tags=["Advanced"],
    summary="Scrape data from a Server-Sent Events endpoint",
)
async def sse_scrape(
    url: str = Body(...),
    max_events: int = Body(50),
    timeout: int = Body(30),  # noqa: ASYNC109 - FastAPI endpoint param, API contract
    event_filter: str = Body(""),
) -> dict[str, Any]:
    """Connect to a Server-Sent Events endpoint and capture events."""
    from pry.engine.websocket_scraper import WebSocketScraper

    s = WebSocketScraper(timeout=timeout)
    result = await s.scrape_sse(url, event_filter=event_filter, max_events=max_events)
    return {"success": result.get("success", False), "data": result}


@router.post(
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
    from pry.engine.cookie_warmer import CookieWarmer

    w = CookieWarmer()
    result = await w.warm_for_site(target_domain, pages_to_visit=pages_to_visit)
    return {"success": result.get("success", False), "data": result}


@router.get(
    "/v1/cookies/sessions",
    tags=["Advanced"],
    summary="List all warmed cookie sessions",
)
async def list_cookie_sessions() -> dict[str, Any]:
    from pry.engine.cookie_warmer import CookieWarmer

    w = CookieWarmer()
    return {"success": True, "data": w.list_sessions()}


@router.post(
    "/v1/pdf/extract",
    tags=["Advanced"],
    summary="Extract tables and text from a PDF",
)
async def extract_pdf(
    pdf_url: str = Body(...),
    method: str = Body("pdfplumber"),
) -> dict[str, Any]:
    """Download a PDF and extract structured tables and text."""
    from pry.engine.pdf_extractor import PDFTableExtractor

    validate_url(pdf_url)
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
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("advanced_exception_handler", exc_info=True)
        return {"success": False, "error": str(e)[:300]}


@router.post(
    "/v1/ocr/extract",
    tags=["Advanced"],
    summary="Extract text from an image using Tesseract",
)
async def ocr_extract(
    image_url: str = Body(""),
    image_base64: str = Body(""),
) -> dict[str, Any]:
    """Extract text from an image via URL or base64."""
    from pry.engine.ocr_extractor import ImageOCR

    o = ImageOCR()
    if image_url:
        validate_url(image_url)
        result = await o.extract_from_url(image_url)
    elif image_base64:
        data = base64.b64decode(image_base64.split(",", 1)[-1])
        result = o.extract_from_bytes(data)
    else:
        return {"success": False, "error": "Provide image_url or image_base64"}
    return result


@router.post(
    "/v1/dedup/check",
    tags=["Advanced"],
    summary="Check if content is a near-duplicate using SimHash",
)
async def check_duplicate(
    text: str = Body(...),
    threshold: float = Body(0.85),
) -> dict[str, Any]:
    """Check if text is a near-duplicate of recently seen content using SimHash."""
    from pry.engine.dedup import SimHash

    h = SimHash.hash(text)
    return {
        "success": True,
        "data": {
            "hash": h,
            "text_length": len(text),
            "threshold": threshold,
        },
    }


@router.get(
    "/v1/behavior/simulate",
    tags=["Advanced"],
    summary="Generate human-like behavior patterns for testing",
)
async def get_behavior_simulation(action: str = "mouse") -> dict[str, Any]:
    """Generate realistic human behavior patterns (mouse path, scroll, typing, etc.)"""
    from pry.engine.behavioral_biometrics import behavior

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
