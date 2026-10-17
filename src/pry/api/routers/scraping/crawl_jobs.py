"""Pry — Firecrawl-compatible async crawl-job surface.

Read/cancel the crawl jobs created by ``POST /v1/crawl`` (webhook mode) and
expose per-URL failures. The job store is the existing ``JobQueue``
(``pry.core.jobqueue``) — no second store, no shadow state. Polling is
read-only, so repeated polls of a terminal job return the same payload.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status

from pry.core.deps import queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Scraping"])

__all__ = ["router"]

# JobQueue states are pending/running/completed/failed; Firecrawl additionally
# has ``cancelled``. Everything else maps onto Firecrawl's public vocabulary.
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_STATUS_MAP = {"pending": "queued", "running": "scraping"}


def _status(job: dict[str, Any]) -> str:
    """Map a stored job status onto the Firecrawl status vocabulary.

    ``cancelled_at`` is a sticky marker: an in-flight crawl task can still
    write ``completed`` after a DELETE, and cancellation must not flip back.
    """
    if job.get("cancelled_at"):
        return "cancelled"
    raw = str(job.get("status") or "pending")
    return raw if raw in _TERMINAL else _STATUS_MAP.get(raw, "queued")


def _pages(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the crawl result pages, tolerating legacy/raw result shapes."""
    result = job.get("result")
    if isinstance(result, dict):
        pages = result.get("pages")
    elif isinstance(result, list):
        pages = result
    else:
        pages = None
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _is_failed(page: dict[str, Any]) -> bool:
    return page.get("status") == "error" or bool(page.get("error"))


def _split(pages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Split pages into successful documents and per-URL failures."""
    failed = [page for page in pages if _is_failed(page)]
    ok = [page for page in pages if not _is_failed(page)]
    return ok, failed


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    pages = _pages(job)
    data, _ = _split(pages)
    body: dict[str, Any] = {
        "id": job["id"],
        "status": _status(job),
        "total": len(pages),
        "completed": len(data),
        "data": data,
    }
    error = job.get("error")
    if error:
        body["error"] = str(error)
    return body


async def _load_job(job_id: str) -> dict[str, Any]:
    """Fetch a crawl job; 404 for unknown ids and other job types."""
    job = await queue.get_job(job_id)
    if not job or job.get("type") != "crawl":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")
    return job


@router.get("/v1/crawl/{job_id}", summary="Get async crawl job status")
async def get_crawl_job(job_id: str) -> dict[str, Any]:
    """Return job status plus completed pages. Idempotent — read-only."""
    return _payload(await _load_job(job_id))


@router.delete("/v1/crawl/{job_id}", summary="Cancel an async crawl job")
async def cancel_crawl_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued/running crawl job (best-effort) and return final status.

    Terminal jobs are left untouched, so a repeated DELETE is idempotent. The
    in-flight task is not force-killed; ``cancelled_at`` makes the status
    sticky so a later completion write cannot resurrect the job.
    """
    job = await _load_job(job_id)
    if _status(job) not in _TERMINAL:
        try:
            await queue.update_job(
                job_id, status="cancelled", cancelled_at=datetime.now(UTC).isoformat()
            )
        except Exception:
            logger.warning("crawl_cancel_failed", extra={"job_id": job_id}, exc_info=True)
        refreshed = await queue.get_job(job_id)
        if refreshed:
            job = refreshed
        if str(job.get("status")) != "cancelled":
            # Best-effort: report the intent even if the store refused the write.
            job = {**job, "status": "cancelled", "cancelled_at": datetime.now(UTC).isoformat()}
    return _payload(job)


@router.get("/v1/crawl/{job_id}/errors", summary="List per-URL crawl failures")
async def crawl_job_errors(job_id: str) -> dict[str, Any]:
    """Return the per-URL failures recorded by a crawl job."""
    job = await _load_job(job_id)
    _, failed = _split(_pages(job))
    return {
        "id": job["id"],
        "status": _status(job),
        "count": len(failed),
        "errors": failed,
    }
