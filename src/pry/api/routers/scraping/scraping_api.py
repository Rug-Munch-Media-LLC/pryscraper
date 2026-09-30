"""Pry — Scraping router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.api.routers.scraping.crawl_adaptive import adaptive_crawl as adaptive_crawl
from pry.core.deps import scraper
from pry.core.errors import ScrapeError
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])

# Re-register the moved route on THIS router. Decorating the imported symbol
# directly (rather than wrapping it) keeps `adaptive_crawl is
# crawl_adaptive.adaptive_crawl` true, so there is no second implementation to
# drift from the one the router dispatches.
router.post(
    "/v1/crawl/adaptive",
    tags=["Scraping"],
    summary="Crawl with adaptive stopping based on content relevance",
)(adaptive_crawl)

__all__ = ["adaptive_crawl", "capture_network", "router", "ultimate_scrape"]


@router.post(
    "/v1/ultimate-scrape", tags=["Scraping"], summary="Scrape with 10-tier anti-bot fallback system"
)
async def ultimate_scrape(
    url: str = Body(..., embed=True),
) -> dict[str, Any]:
    """Scrape any URL using Pry's ultimate 10-tier anti-detection system.

    Automatically tries: direct → cloudscraper → FlareSolverr →
    undetected-chromedriver → Playwright → Googlebot → Archive.org → Google Cache

    Returns the first successful result with the method used.

    **Request body**

    ```json
    {
      "url": "https://example.com"
    }
    ```

    **Response**

    ```json
    {
      "success": true,
      "data": {
        "url": "https://example.com",
        "method": "direct",
        "content": "<!DOCTYPE html>...",
        "content_length": 12345
      }
    }
    ```

    **x402 payment**: this endpoint is free and always public. Paid scraping
    operations (e.g. actor presets, domain data) are gated behind x402
    micropayments — see `GET /v1/x402/pricing` for the price list.
    """
    from pry.engine.ultimate_scraper import UltimateScraper

    # SSRF gate before the 10-tier fetch chain.
    validate_url(url)
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


@router.post(
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
    # SSRF gate: the fallback raw-HTML fetch below also uses this URL.
    validate_url(url)
    from pry.engine.network import (
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
            resp = await safe_get(client, url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
        except (httpx.HTTPError, httpx.RequestError):
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


logger = logging.getLogger(__name__)
