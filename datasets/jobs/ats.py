"""Multi-ATS job board ingestion for Pry — data-driven thin loader.

Aggregates job listings from the major applicant-tracking systems with
free, no-auth JSON boards (Greenhouse, Lever, Ashby, Workday, Workable,
Breezy HR, SmartRecruiters, Recruitee, Jobvite). Board endpoints, field
mappings and normalization rules live in the co-located ``ats.json``;
the generic verbs that interpret those specs live in ``_ats_spec``.
This module is the thin loader: HTTP + retry, TTL cache, and the public
entry points folding raw payloads into the common listing/detail
schemas. Every public function is ``async`` and never raises — network
errors, timeouts, HTTP error statuses, bad JSON and unexpected shapes
all degrade to ``[]`` / ``{}``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from datasets.jobs import _ats_spec as spec
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_DATA: dict[str, Any] = json.loads((Path(__file__).with_name("ats.json")).read_text())
SUPPORTED_BOARDS: tuple[str, ...] = tuple(_DATA["boards"])
SEARCH_COMPANIES: tuple[tuple[str, str], ...] = tuple(map(tuple, _DATA["search_companies"]))

_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.2,
    max_delay=1.0,
    retryable_exceptions=(httpx.HTTPError, json.JSONDecodeError),
)
# BLE001 is enforced: catch specific exception types only.
_SAFE_EXCEPTIONS: tuple[type[Exception], ...] = (httpx.HTTPError, json.JSONDecodeError, OSError)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_CACHE_TTL_SECONDS = 300.0
_list_cache: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}


def _clear_cache() -> None:
    """Clear the in-memory listing cache (used by tests and maintenance)."""
    _list_cache.clear()


async def _request(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    """HTTP request + JSON-decode with timeout and bounded retry; None on failure.

    A JSON ``payload`` switches to a POST with browser-like same-origin headers
    (required by the Workday CXS endpoint).
    """

    async def _one() -> Any:
        headers = dict(_HEADERS)
        if payload is not None:
            headers["Content-Type"] = "application/json"
            host = url.split("/")[2]
            headers["Origin"] = f"https://{host}"
            headers["Referer"] = f"https://{host}/"
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            response = await client.request(method, url, json=payload)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_request_failed", extra={"url": url})
        return None


async def _fetch_list(spec_: dict[str, Any], company: str, site: str, limit: int) -> Any:
    """Fetch a board's raw list payload (GET, or POST for Workday CXS)."""
    if spec_["method"] == "POST":
        url = spec_["url"].format(company=company, site=site)
        payload = {"appliedFacets": {}, "limit": limit, "offset": 0, "searchText": ""}
        return await _request("POST", url, payload=payload)
    return await _request("GET", spec_["url"].format(company=company))


async def list_jobs(
    company: str, board: str = "greenhouse", limit: int = 50, *, site: str | None = None
) -> list[dict[str, Any]]:
    """List job postings for a company from one ATS board.

    Returns the common listing schema, newest-first as provided by the
    board, truncated to ``limit``. Never raises — ``[]`` on any failure.
    """
    board_spec = _DATA["boards"].get(board)
    if board_spec is None or not company or not company.strip():
        return []
    try:
        limit = max(1, min(int(limit or 50), 500))
    except (TypeError, ValueError):
        limit = 50
    company = company.strip()
    site_name = site.strip() if site and site.strip() else company
    cache_key = (board, company, site_name)
    cached = _list_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] <= _CACHE_TTL_SECONDS:
        return cached[1][:limit]
    _list_cache.pop(cache_key, None)
    try:
        data = await _fetch_list(board_spec, company, site_name, limit)
        items = [
            spec.norm(j, board_spec, company)
            for j in spec.extract(data, board_spec)
            if isinstance(j, dict)
        ]
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_list_failed", extra={"board": board, "company": company})
        return []
    _list_cache[cache_key] = (time.monotonic(), items)
    return items[:limit]


async def search_jobs(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Cross-board keyword search (title + location) over known boards."""
    if not query or not query.strip():
        return []
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    needle = query.strip().lower()
    results: list[dict[str, Any]] = []
    for company, board in SEARCH_COMPANIES:
        for item in await list_jobs(company, board=board, limit=50):
            hay = f"{item.get('title') or ''} {item.get('location') or ''}".lower()
            if needle in hay:
                results.append(item)
    results.sort(key=lambda item: item.get("posted_at") or "", reverse=True)
    return results[:limit]


async def _find_in_list(
    board_spec: dict[str, Any], company: str, job_id: str
) -> dict[str, Any] | None:
    """Fetch a board's list and locate one posting by id."""
    id_key = board_spec.get("id_key", "id")
    data = await _fetch_list(board_spec, company, company, 20)
    for item in spec.extract(data, board_spec):
        if isinstance(item, dict):
            candidate = str(item.get(id_key) or item.get("externalPath") or "")
            if candidate == job_id:
                return item
    return None


async def get_job(
    job_id: str, board: str = "greenhouse", *, company: str | None = None
) -> dict[str, Any]:
    """Fetch one job's full detail (description / requirements / compensation).

    ``company`` is required to build the board URL; returns ``{}`` when it
    is missing or the board responds with an error.
    """
    board_spec = _DATA["boards"].get(board)
    if not job_id or board_spec is None or not company or not company.strip():
        return {}
    company = company.strip()
    try:
        if board_spec.get("detail_url"):
            data = await _request(
                "GET", board_spec["detail_url"].format(company=company, job_id=job_id)
            )
            if not isinstance(data, dict):
                return {}
            if board_spec.get("wrap"):
                inner = data.get(board_spec["wrap"])
                if not isinstance(inner, dict) or not inner:
                    return {}
                data = inner
            return spec.detail(data, board_spec["detail"], company, job_id)
        item = await _find_in_list(board_spec, company, job_id)
        return spec.detail(item, board_spec["detail"], company, job_id) if item else {}
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_job_failed", extra={"board": board, "company": company})
        return {}
