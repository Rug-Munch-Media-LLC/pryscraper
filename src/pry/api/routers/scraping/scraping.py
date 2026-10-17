"""Pry — Scraping router (scrape, crawl, map, batch, detect).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import copy
import logging
import random
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, HTTPException, Request

from pry.api.client import get_client
from pry.api.routers.scraping.scraping_models import CrawlRequest, MapRequest, ScrapeRequest
from pry.core.audit import audit_event
from pry.core.deps import cache, extractor, queue, scraper
from pry.core.errors import ExternalServiceError, InvalidRequestError, PryError, ScrapeError
from pry.core.observability import track_scrape
from pry.core.settings import settings
from pry.engine.scraper import BlockDetector
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])

__all__ = ["CrawlRequest", "MapRequest", "ScrapeRequest", "router"]


def _audit_http(http_request: Request, operation: str, url: str, outcome: str) -> None:
    """Record an audit row. Host only — never the full URL or query string.

    Successes are sampled 1:100; denials and errors are always recorded.
    """
    if outcome == "success" and random.random() >= 0.01:  # noqa: S311 - sampling
        return
    record = http_request.scope.get("pry_api_key") or {}
    audit_event(
        "scrape_request",
        actor=str(record.get("key_id") or "")[:8],
        path=http_request.url.path,
        host=urlsplit(url).hostname or "",
        operation=operation,
        outcome=outcome,
    )


def _deny_if_blocked(http_request: Request, operation: str, url: str) -> None:
    """451 before any fetch when the host is on the compliance block list."""
    from pry.api.routers.integrations.gdpr import is_domain_blocked

    host = urlsplit(url).hostname or ""
    if host and is_domain_blocked(host):
        _audit_http(http_request, operation, url, "denied")
        raise HTTPException(status_code=451, detail="Domain blocked for compliance reasons")


async def _run_crawl_job(job_id: str, request: CrawlRequest) -> None:
    try:
        pages = await scraper.crawl(
            request.url, {"max_pages": request.maxPages, "max_depth": request.maxDepth}
        )
        await queue.complete_job(job_id, {"pages": pages})
    except Exception as e:
        logger.exception("crawl_job_failed", extra={"job_id": job_id, "url": request.url})
        await queue.fail_job(job_id, str(e))


def _log_crawl_job_failure(task: asyncio.Task[Any]) -> None:
    exc = task.exception()
    if exc:
        logger.error("crawl_task_unhandled_error", extra={"error": str(exc)})


@router.post("/v1/scrape", summary="Scrape a single URL")
async def scrape(request: ScrapeRequest, http_request: Request) -> dict[str, Any]:
    """Scrape a URL. Auto-bypasses Cloudflare. Returns markdown or JSON."""
    _deny_if_blocked(http_request, "scrape", request.url)
    cache_opts = {"bypass_cloudflare": request.bypassCloudflare, "js_render": request.jsRender}
    cached = cache.get(request.url, cache_opts)
    if cached:
        out = copy.deepcopy(cached)
        md = out.get("data", {}).get("markdown", "")
        out["data"]["markdown"] = md[request.offset : request.offset + request.limit]
        out["data"]["metadata"]["offset"] = request.offset
        out["data"]["metadata"]["total"] = len(md)
        out["_cached"] = True
        _audit_http(http_request, "scrape", request.url, "success")
        return out
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
            raise ScrapeError(
                result.get("error", "Scrape failed"),
                verdict=result.get("verdict"),
                tiers_attempted=result.get("tiers_attempted"),
                tiers_failed=result.get("tiers_failed"),
            )
        content = result.get("content", "")
        response: dict[str, Any] = {
            "success": True,
            "data": {
                "markdown": content,
                "metadata": {
                    "url": request.url,
                    "method": result.get("method", "unknown"),
                    "title": result.get("title", ""),
                    "description": result.get("description", ""),
                },
            },
        }
        if request.jsonSchema:
            response["data"]["json"] = await extractor.extract(content, request.jsonSchema)
        cache.set(request.url, response, cache_opts)
        out = copy.deepcopy(response)
        out["data"]["markdown"] = content[request.offset : request.offset + request.limit]
        out["data"]["metadata"]["offset"] = request.offset
        out["data"]["metadata"]["total"] = len(content)
        _audit_http(http_request, "scrape", request.url, "success")
        return out
    except PryError:
        _audit_http(http_request, "scrape", request.url, "error")
        raise
    except Exception as e:
        _audit_http(http_request, "scrape", request.url, "error")
        raise ExternalServiceError(str(e)) from e


@router.post("/v1/detect-block", summary="Detect if a site is blocking the scraper")
async def detect_block(url: str = Body(...)) -> dict[str, Any]:
    """Detect anti-bot protection (tier, vendor, confidence)."""
    validate_url(url)
    detector = BlockDetector()
    results = []
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
        results.append(
            {
                "method": "direct",
                "status": resp.status_code,
                **detector.detect(resp.text, resp.status_code, dict(resp.headers)),
            }
        )
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("scraping_exception_handler", exc_info=True)
        results.append({"method": "direct", "error": str(e)})
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
                results.append(
                    {
                        "method": "flaresolverr",
                        "status": fs_status,
                        **detector.detect(fs_html, fs_status),
                    }
                )
            else:
                results.append({"method": "flaresolverr", "error": f"HTTP {fs_resp.status_code}"})
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("scraping_exception_handler", exc_info=True)
        results.append({"method": "flaresolverr", "error": str(e)})
    return {"success": True, "data": {"url": url, "results": results}}


@router.post("/v1/capture/lazy", summary="Detect and handle lazy-loaded content")
async def detect_lazy_content(
    url: str = Body(...), auto_scroll: bool = Body(True), max_scrolls: int = Body(5)
) -> dict[str, Any]:
    """Detect lazy loading and optionally generate auto-scroll JS."""
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
    return {
        "success": True,
        "data": {
            "url": url,
            "detection": detection,
            "has_lazy_content": any(detection.values()),
            "scroll_script": generate_scroll_script(max_scrolls=max_scrolls) if auto_scroll else "",
            "load_more_script": generate_load_more_script() if auto_scroll else "",
        },
    }


@router.post("/v1/crawl", summary="Crawl multiple pages from a URL")
async def crawl(request: CrawlRequest, http_request: Request) -> dict[str, Any]:
    """Crawl multiple pages from a URL. Supports async webhooks."""
    _deny_if_blocked(http_request, "crawl", request.url)
    if request.webhook:
        job_id = await queue.create_job("crawl", request.model_dump(), webhook=request.webhook)
        task = asyncio.create_task(_run_crawl_job(job_id, request))
        task.add_done_callback(_log_crawl_job_failure)
        _audit_http(http_request, "crawl", request.url, "success")
        return {"success": True, "data": {"id": job_id, "status": "pending"}}
    try:
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
    except Exception:
        _audit_http(http_request, "crawl", request.url, "error")
        raise
    _audit_http(http_request, "crawl", request.url, "success")
    return {"success": True, "data": {"id": "sync", "url": request.url, "pages": pages}}


@router.post("/v1/map", summary="Discover URLs on a site")
async def map_pages(request: MapRequest) -> dict[str, Any]:
    """Discover URLs on a site."""
    validate_url(request.url)
    try:
        with track_scrape(method="map"):
            urls = await scraper.map_urls(request.url, {"limit": request.limit})
    except RuntimeError as e:
        raise ScrapeError(str(e)) from e
    return {"success": True, "data": {"links": urls}}


@router.post("/v1/batch", summary="Scrape multiple URLs in parallel")
async def batch_scrape(
    http_request: Request,
    urls: list[str] = Body(...),
    timeout: int = 30,  # noqa: ASYNC109 - FastAPI endpoint param, API contract
) -> dict[str, Any]:
    """Scrape multiple URLs in parallel (max 50 per batch)."""
    if len(urls) > 50:
        raise InvalidRequestError("Max 50 URLs per batch")
    for url in urls:
        _deny_if_blocked(http_request, "batch", url)
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
    outcome = "error" if any(isinstance(r, BaseException) for r in results) else "success"
    _audit_http(http_request, "batch", urls[0], outcome)
    return {"success": True, "data": {"pages": pages, "total": len(pages)}}
