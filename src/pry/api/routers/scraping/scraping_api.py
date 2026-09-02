"""Pry — Scraping router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
import pydantic
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.core.deps import scraper
from pry.core.errors import ScrapeError
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])


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


@router.post(
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
    from pry.engine.adaptive import AdaptiveCrawler

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
        except pydantic.ValidationError as e:
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


logger = logging.getLogger(__name__)
