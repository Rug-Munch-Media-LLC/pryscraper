"""Federal procurement opportunities — free SAM.gov Opportunities API v2.

SAM.gov publishes federal solicitations / contract opportunities through a
public REST API. Anonymous access is not supported: a free API key
(https://sam.gov/content/webservices) must be set via the ``PRY_SAM_API_KEY``
env var and is sent as the ``api_key`` query parameter. Without a key every
function degrades to ``[]`` / ``{}`` (never raises) — the module still works
fully when a key is configured.

Contract
--------
* :func:`search_opportunities` — async, never raises, returns a ``list``
  (``[]`` on failure). Searches federal opportunities by keyword ``query``.
* :func:`get_opportunity` — async, never raises, returns a ``dict`` (``{}``
  on failure). Fetches one opportunity by its SAM.gov ``noticeId``.

Result shapes
-------------
``search_opportunities`` returns a list of:

    {
        "id": "3488234",
        "title": "Z--TEST Presolicitation",
        "agency": "OFFICE OF ...",
        "type": "Presolicitation",
        "naics": "531210",
        "set_aside": "Total Small Business Set-Aside (FAR 19.5)",
        "due_date": "2026-01-01 12:00:00+00",
        "url": "https://sam.gov/opp/3488234/view",
        "source": "sam_gov",
    }

``get_opportunity`` returns the same shape (``{}`` when the notice id does
not exist).

Free-API terms: https://api.sam.gov/opportunities/v2/search — the v2 API
caps page size at 200. Backoff: 2 retries, exponential (0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.sam.gov/opportunities/v2/search"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-gov/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# Free API key: https://sam.gov/content/webservices
_API_KEY_ENV = "PRY_SAM_API_KEY"
_MAX_LIMIT = 200  # SAM.gov Opportunities v2 caps page size at 200


def _api_key() -> str:
    """Return the configured SAM.gov API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _map_opportunity(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a SAM.gov Opportunities v2 object onto the canonical record."""
    notice_id = _as_text(raw.get("noticeId"))
    url = _as_text(raw.get("url"))
    if not url and notice_id:
        url = f"https://sam.gov/opp/{notice_id}/view"
    return {
        "id": notice_id,
        "title": _as_text(raw.get("title")),
        "agency": _as_text(raw.get("agency")),
        "type": _as_text(raw.get("typeOfNotice")) or _as_text(raw.get("noticeType")),
        "naics": _as_text(raw.get("naicsCode")),
        "set_aside": _as_text(raw.get("setAside"))
        or _as_text(raw.get("typeOfSetAsideDescription")),
        "due_date": _as_text(raw.get("responseDeadLine")) or _as_text(raw.get("responseDate")),
        "url": url,
        "source": "sam_gov",
    }


async def _fetch_opportunities(params: dict[str, str]) -> list[dict[str, Any]] | None:
    """GET the SAM.gov Opportunities v2 search and return ``opportunitiesData``.

    Returns ``None`` on any failure (network, non-2xx, malformed payload).
    """

    async def _one() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("sam.gov payload is not an object")
        data = payload.get("opportunitiesData")
        if not isinstance(data, list):
            raise ValueError("sam.gov payload missing opportunitiesData list")
        return data

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def search_opportunities(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search federal contract opportunities by keyword.

    Args:
        query: Keyword search string (e.g. ``"aircraft maintenance"``).
        limit: Max results to return (1-200; API caps page size at 200).

    Returns:
        A list of opportunity records (see module docstring). ``[]`` on
        failure (no API key, network error, bad payload). Never raises.
    """
    try:
        return await _search_opportunities(query, limit)
    except Exception:
        logger.exception("gov_procurement_search_crashed", extra={"query": query})
        return []


async def _search_opportunities(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    key = _api_key()
    if not key:
        logger.warning("gov_sam_api_key_missing")
        return []
    params: dict[str, str] = {
        "api_key": key,
        "q": query.strip(),
        "limit": str(max(1, min(int(limit), _MAX_LIMIT))),
        "page": "0",
    }
    data = await _fetch_opportunities(params)
    if data is None:
        return []
    return [_map_opportunity(raw) for raw in data if isinstance(raw, dict)]


async def get_opportunity(notice_id: str | int) -> dict[str, Any]:
    """Fetch one SAM.gov opportunity by its notice id.

    Args:
        notice_id: SAM.gov ``noticeId`` (int or numeric string).

    Returns:
        Opportunity record (see module docstring) or ``{}`` on failure
        (unknown id, no API key, network error). Never raises.
    """
    try:
        return await _get_opportunity(notice_id)
    except Exception:
        logger.exception("gov_procurement_get_crashed", extra={"notice_id": notice_id})
        return {}


async def _get_opportunity(notice_id: str | int) -> dict[str, Any]:
    if notice_id is None or str(notice_id).strip() == "":
        return {}
    key = _api_key()
    if not key:
        logger.warning("gov_sam_api_key_missing")
        return {}
    params: dict[str, str] = {
        "api_key": key,
        "noticeId": str(notice_id).strip(),
        "limit": "1",
        "page": "0",
    }
    data = await _fetch_opportunities(params)
    if not data:
        return {}
    return _map_opportunity(data[0])
