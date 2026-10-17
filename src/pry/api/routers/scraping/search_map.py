"""Pry — Firecrawl-parity search and site-map endpoints.

Two routes Firecrawl exposes that Pry previously served over MCP only:

* ``POST /v1/search`` — web search (SearXNG, DuckDuckGo fallback) returning
  ``{query, results: [{url, title, description}]}``.
* ``POST /v1/map`` — same-origin URL discovery from a site's ``sitemap.xml``,
  falling back to the existing scraper's link extraction.

Both are SSRF-guarded (every URL validated, every sitemap fetch goes through
``url_guard.safe_get``) and both are x402-priced. Pricing lives in
``X402_PRICING["search"]`` / ``PAID_ENDPOINTS["/v1/search"]``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from pry.api.routers.scraping import scraping as _legacy_scraping
from pry.core.deps import search_web
from pry.core.errors import ScrapeError
from pry.engine.url_guard import safe_get, validate_url_async

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])

SEARCH_MAX_LIMIT = 20
MAP_MAX_LIMIT = 500

_USER_AGENT = "Mozilla/5.0 (compatible; PryScraper/3.0; +https://pryscraper.com)"
_SITEMAP_TIMEOUT_S = 10.0
_POLITENESS_DELAY_S = 0.25
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


class SearchRequest(BaseModel):
    """Body for ``POST /v1/search``."""

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=SEARCH_MAX_LIMIT)


class MapRequest(BaseModel):
    """Body for ``POST /v1/map``."""

    url: str = Field(min_length=1, max_length=2048)
    limit: int = Field(default=50, ge=1, le=MAP_MAX_LIMIT)


@router.post("/v1/search", summary="Search the web")
async def search(request: SearchRequest) -> dict[str, Any]:
    """Search the web and return titles, URLs and descriptions."""
    payload = await search_web(request.query, request.limit)
    results = [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "description": item.get("snippet", ""),
        }
        for item in payload.get("results", [])[: request.limit]
        if item.get("url")
    ]
    return {"query": request.query, "results": results}


def _same_origin(base: str, candidates: list[str]) -> list[str]:
    """Return unique, fragment-free http(s) links sharing ``base``'s host."""
    origin = urlparse(base).netloc
    seen: set[str] = set()
    links: list[str] = []
    for raw in candidates:
        candidate = urljoin(base, raw.strip())
        parsed = urlparse(candidate)
        if parsed.scheme not in ("http", "https") or parsed.netloc != origin:
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        links.append(clean)
    return links


async def _sitemap_links(client: httpx.AsyncClient, url: str) -> list[str]:
    """Fetch ``/sitemap.xml`` through the SSRF guard. Returns [] on any failure."""
    sitemap_url = urljoin(url, "/sitemap.xml")
    try:
        await validate_url_async(sitemap_url)
        response = await safe_get(client, sitemap_url, timeout=_SITEMAP_TIMEOUT_S)
        if response.status_code != 200:
            return []
        return _LOC_RE.findall(response.text)
    except Exception as exc:  # noqa: BLE001 - absence of a sitemap is normal
        logger.debug("sitemap_unavailable", extra={"url": sitemap_url, "error": str(exc)})
        return []


@router.post("/v1/map", summary="Discover URLs on a site")
async def map_site(request: MapRequest) -> dict[str, Any]:
    """Map a site: sitemap first, then the scraper's same-origin link crawl."""
    url = await validate_url_async(request.url)
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/xml,text/html,*/*"}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_SITEMAP_TIMEOUT_S + 5.0),
        follow_redirects=False,
        headers=headers,
    ) as client:
        links = _same_origin(url, await _sitemap_links(client, url))

    if not links:
        # One request to the origin already happened; wait before the next.
        await asyncio.sleep(_POLITENESS_DELAY_S)
        try:
            # Resolved through the scraping router module on purpose: it is the
            # single existing scraper binding (and the seam tests patch).
            found = await _legacy_scraping.scraper.map_urls(url, {"limit": request.limit})
        except RuntimeError as exc:
            raise ScrapeError(str(exc)) from exc
        links = _same_origin(url, found)

    links = links[: request.limit]
    return {
        "url": url,
        "links": [{"url": link} for link in links],
        "count": len(links),
        # Additive compatibility with the previous /v1/map response shape so
        # existing clients (and the scraping-router contract tests) keep working.
        "success": True,
        "data": {"links": links},
    }
