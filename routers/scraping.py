"""Pry — Scraping router (scrape, crawl, map, batch, detect).

Split from api.py on the api-router-split refactor. Replaces inline
Scraping-tagged endpoints from api.py. Behavior is identical.

Endpoints (6):
  POST /v1/scrape          — Scrape a single URL
  POST /v1/detect-block    — Detect anti-bot protection
  POST /v1/capture/lazy    — Detect lazy-loaded content
  POST /v1/crawl           — Crawl multiple pages
  POST /v1/map             — Discover URLs on a site
  POST /v1/batch           — Scrape multiple URLs in parallel

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body
from pydantic import BaseModel

from pry.api.client import get_client
from pry.core.deps import cache, extractor, queue, scraper
from pry.core.errors import ExternalServiceError, InvalidRequestError, PryError, ScrapeError
from pry.core.observability import track_scrape
from pry.core.settings import settings
from pry.engine.scraper import BlockDetector
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])


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


# ── Internal helpers ──


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


# ── Scrape ──


@router.post("/v1/scrape", summary="Scrape a single URL")
async def scrape(request: ScrapeRequest) -> dict[str, Any]:
    """Scrape a URL. Auto-bypasses Cloudflare. Returns markdown or JSON."""
    # Check cache
    cache_opts = {"bypass_cloudflare": request.bypassCloudflare, "js_render": request.jsRender}
    cached = cache.get(request.url, cache_opts)
    if cached:
        cached["_cached"] = True
        return cached

    try:
        with track_scrape(method="direct"):
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


@router.post("/v1/detect-block", summary="Detect if a site is blocking the scraper")
async def detect_block(url: str = Body(...)) -> dict[str, Any]:
    """Detect what kind of anti-bot protection a site is using.

    Returns detection tier, vendor (Cloudflare/DataDome/etc.), and confidence.
    Useful for debugging scraping issues.
    """
    # SSRF gate: reject private/loopback/metadata targets before any probe.
    validate_url(url)
    detector = BlockDetector()
    results = []

    # Test direct
    try:
        client = await get_client()
        resp = await safe_get(
            client,
            url,
            timeout=15,
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
    except (httpx.HTTPError, httpx.RequestError) as e:
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
    except (httpx.HTTPError, httpx.RequestError) as e:
        results.append({"method": "flaresolverr", "error": str(e)})

    return {"success": True, "data": {"url": url, "results": results}}


@router.post("/v1/capture/lazy", summary="Detect and handle lazy-loaded content")
async def detect_lazy_content(
    url: str = Body(...),
    auto_scroll: bool = Body(True),
    max_scrolls: int = Body(5),
) -> dict[str, Any]:
    """Detect lazy loading and infinite scroll patterns on a page.

    Optionally generate JS to auto-scroll and load all content.
    """
    # SSRF gate: the fallback raw-HTML fetch below also uses this URL.
    validate_url(url)
    from pry.engine.lazy_load import (
        detect_lazy_loading,
        generate_load_more_script,
        generate_scroll_script,
    )

    with track_scrape(method="lazy"):
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


@router.post("/v1/crawl", summary="Crawl multiple pages from a URL")
async def crawl(request: CrawlRequest) -> dict[str, Any]:
    """Crawl multiple pages from a URL. Supports async webhooks."""
    if request.webhook:
        job_id = await queue.create_job("crawl", request.model_dump(), webhook=request.webhook)
        task = asyncio.create_task(_run_crawl_job(job_id, request))
        task.add_done_callback(_log_crawl_job_failure)
        return {"success": True, "data": {"id": job_id, "status": "pending"}}

    with track_scrape(method="crawl"):
        pages = await scraper.crawl(
            request.url,
            {
                "max_pages": request.maxPages,
                "max_depth": request.maxDepth,
                "timeout": request.scrapeOptions.get("timeout", 60)
                if request.scrapeOptions
                else 60,
            },
        )
    return {"success": True, "data": {"id": "sync", "url": request.url, "pages": pages}}


# ── Map ──


@router.post("/v1/map", summary="Discover URLs on a site")
async def map_pages(request: MapRequest) -> dict[str, Any]:
    """Discover URLs on a site."""
    # SSRF gate: map_urls -> _extract_links fetches the target directly.
    validate_url(request.url)
    with track_scrape(method="map"):
        urls = await scraper.map_urls(request.url, {"limit": request.limit})
    return {"success": True, "data": {"links": urls}}


# ── Batch ──


@router.post("/v1/batch", summary="Scrape multiple URLs in parallel")
async def batch_scrape(
    urls: list[str] = Body(...),
    timeout: int = 30,  # noqa: ASYNC109 - FastAPI endpoint param, API contract
) -> dict[str, Any]:
    """Scrape multiple URLs in parallel. Firecrawl charges extra for batch."""
    if len(urls) > 50:
        raise InvalidRequestError("Max 50 URLs per batch")
    with track_scrape(method="batch"):
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
