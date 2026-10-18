"""Pry — ``POST /v1/batch`` (sync list, or async queue-backed batch).

Sync: a JSON array of URLs (legacy shape) or ``{"urls": [...]}`` returns all
pages inline, capped at 50 URLs. Async: ``{"urls": [...], "webhook": ...}`` or
``{"urls": [...], "async": true}`` creates a job on the existing ``JobQueue``
(``pry.core.jobqueue``) and returns its id; poll ``GET /v1/batch/{job_id}``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from pry.api.routers.scraping.http_guards import audit_http, deny_if_blocked
from pry.api.routers.scraping.seams import bindings
from pry.core.observability import track_scrape

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_URLS = 50
_UNPROCESSABLE = 422
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_STATUS_MAP = {"pending": "queued", "running": "scraping"}


def _parse_body(body: Any, query_timeout: int) -> tuple[list[str], int, str | None, bool]:
    """Normalise the legacy list body and the Firecrawl object body."""
    if isinstance(body, list):
        urls, timeout, webhook, is_async = body, query_timeout, None, False
    elif isinstance(body, dict):
        urls = body.get("urls")
        timeout = int(body.get("timeout") or query_timeout)
        webhook = body.get("webhook") or None
        is_async = bool(body.get("async")) or bool(webhook)
    else:
        raise HTTPException(_UNPROCESSABLE, "Body must be URLs")
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise HTTPException(_UNPROCESSABLE, "Body must be URLs")
    return urls, timeout, webhook, is_async


def _batch_pages(urls: list[str], results: list[Any]) -> list[dict[str, Any]]:
    """Normalise per-URL results; an exception becomes an ``error`` entry."""
    pages: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            pages.append({"url": urls[i], "error": str(result)})
        elif isinstance(result, dict):
            pages.append(
                {
                    "url": urls[i],
                    "markdown": result.get("content", ""),
                    "method": result.get("method", "unknown"),
                }
            )
    return pages


async def _scrape_all(urls: list[str], timeout_s: int) -> list[dict[str, Any]]:
    """Scrape every URL concurrently through the shared scraper."""
    scraper = bindings().scraper
    tasks = [scraper.scrape(u, {"timeout": timeout_s, "bypass_cloudflare": True}) for u in urls]
    return await asyncio.gather(*tasks, return_exceptions=True)


async def _run_batch_job(job_id: str, urls: list[str], timeout_s: int) -> None:
    """Execute a queued batch and record the result (webhook fires in queue)."""
    ctx = bindings()
    try:
        pages = _batch_pages(urls, await _scrape_all(urls, timeout_s))
        await ctx.queue.complete_job(job_id, {"pages": pages, "total": len(pages)})
    except Exception as e:
        logger.exception("batch_job_failed", extra={"job_id": job_id})
        await ctx.queue.fail_job(job_id, str(e))


def _log_job_failure(task: asyncio.Task[Any]) -> None:
    if exc := task.exception():
        logger.error("batch_task_unhandled_error", extra={"error": str(exc)})


@router.post("/v1/batch", summary="Scrape multiple URLs in parallel")
async def batch_scrape(
    http_request: Request,
    body: Any = Body(...),
    timeout: int = 30,  # noqa: ASYNC109 - FastAPI query param, API contract
) -> dict[str, Any]:
    """Scrape up to 50 URLs; async/webhook mode returns a job id."""
    urls, timeout, webhook, is_async = _parse_body(body, timeout)
    if len(urls) > MAX_URLS:
        raise HTTPException(_UNPROCESSABLE, f"Max {MAX_URLS} URLs per batch")
    for url in urls:
        deny_if_blocked(http_request, "batch", url)
    if is_async:
        ctx = bindings()
        job_id = await ctx.queue.create_job(
            "batch",
            {"urls": urls, "timeout": timeout},
            webhook=webhook,
            timeout_s=max(300, len(urls) * timeout),
        )
        task = asyncio.create_task(_run_batch_job(job_id, urls, timeout))
        task.add_done_callback(_log_job_failure)
        audit_http(http_request, "batch", urls[0] if urls else "", "success")
        return {"success": True, "id": job_id, "status": "pending", "data": {"id": job_id}}
    with track_scrape(method="batch"):
        results = await _scrape_all(urls, timeout)
    pages = _batch_pages(urls, results)
    outcome = "error" if any(isinstance(r, BaseException) for r in results) else "success"
    audit_http(http_request, "batch", urls[0] if urls else "", outcome)
    return {"success": True, "data": {"pages": pages, "total": len(pages)}}


@router.get("/v1/batch/{job_id}", summary="Get async batch job status")
async def get_batch_job(job_id: str) -> dict[str, Any]:
    """Return a queued batch's status and completed pages. Read-only."""
    job = await bindings().queue.get_job(job_id)
    if not job or job.get("type") != "batch":
        raise HTTPException(404, detail="Batch job not found")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    pages = result.get("pages") if isinstance(result.get("pages"), list) else []
    raw = str(job.get("status") or "pending")
    body: dict[str, Any] = {
        "id": job["id"],
        "status": raw if raw in _TERMINAL else _STATUS_MAP.get(raw, "queued"),
        "total": len(pages),
        "completed": len([p for p in pages if not p.get("error")]),
        "data": pages,
    }
    if job.get("error"):
        body["error"] = str(job["error"])
    return body
