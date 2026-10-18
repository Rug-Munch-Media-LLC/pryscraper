"""Pry — ``POST /v1/crawl`` (sync + webhook-driven multi-page crawl).

``/v1/map`` is not duplicated here: it lives in ``search_map.py``, which is
mounted once by ``app_factory`` (a second registration would shadow it).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request

from pry.api.routers.scraping.http_guards import audit_http, deny_if_blocked
from pry.api.routers.scraping.scraping_models import CrawlRequest  # noqa: TC001 - runtime
from pry.api.routers.scraping.seams import bindings
from pry.core.observability import track_scrape

logger = logging.getLogger(__name__)

router = APIRouter()


async def _run_crawl_job(job_id: str, request: CrawlRequest) -> None:
    ctx = bindings()
    try:
        pages = await ctx.scraper.crawl(
            request.url, {"max_pages": request.maxPages, "max_depth": request.maxDepth}
        )
        await ctx.queue.complete_job(job_id, {"pages": pages})
    except Exception as e:
        logger.exception("crawl_job_failed", extra={"job_id": job_id, "url": request.url})
        await ctx.queue.fail_job(job_id, str(e))


def _log_crawl_job_failure(task: asyncio.Task[Any]) -> None:
    exc = task.exception()
    if exc:
        logger.error("crawl_task_unhandled_error", extra={"error": str(exc)})


async def _crawl_sync(request: CrawlRequest) -> dict[str, Any]:
    """Run the crawl inline and shape the synchronous response body."""
    timeout = request.scrapeOptions.get("timeout", 60) if request.scrapeOptions else 60
    with track_scrape(method="crawl"):
        pages = await bindings().scraper.crawl(
            request.url,
            {"max_pages": request.maxPages, "max_depth": request.maxDepth, "timeout": timeout},
        )
    return {"success": True, "data": {"id": "sync", "url": request.url, "pages": pages}}


@router.post("/v1/crawl", summary="Crawl multiple pages from a URL")
async def crawl(request: CrawlRequest, http_request: Request) -> dict[str, Any]:
    """Crawl multiple pages from a URL. Supports async webhooks."""
    deny_if_blocked(http_request, "crawl", request.url)
    if request.webhook:
        job_id = await bindings().queue.create_job(
            "crawl", request.model_dump(), webhook=request.webhook
        )
        task = asyncio.create_task(_run_crawl_job(job_id, request))
        task.add_done_callback(_log_crawl_job_failure)
        audit_http(http_request, "crawl", request.url, "success")
        return {"success": True, "data": {"id": job_id, "status": "pending"}}
    try:
        response = await _crawl_sync(request)
    except Exception:
        audit_http(http_request, "crawl", request.url, "error")
        raise
    audit_http(http_request, "crawl", request.url, "success")
    return response
