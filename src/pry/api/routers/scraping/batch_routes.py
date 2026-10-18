"""Pry — ``POST /v1/batch`` (parallel scrape of up to 50 URLs).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Request

from pry.api.routers.scraping.http_guards import audit_http, deny_if_blocked
from pry.api.routers.scraping.seams import bindings
from pry.core.errors import InvalidRequestError
from pry.core.observability import track_scrape

router = APIRouter()


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
        deny_if_blocked(http_request, "batch", url)
    scraper = bindings().scraper
    with track_scrape(method="batch"):
        tasks = [scraper.scrape(u, {"timeout": timeout, "bypass_cloudflare": True}) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    pages = _batch_pages(urls, results)
    outcome = "error" if any(isinstance(r, BaseException) for r in results) else "success"
    audit_http(http_request, "batch", urls[0], outcome)
    return {"success": True, "data": {"pages": pages, "total": len(pages)}}
