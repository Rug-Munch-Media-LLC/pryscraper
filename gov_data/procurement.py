"""Federal/EU procurement opportunities — SAM.gov, grants.gov, TED.

SAM.gov publishes federal solicitations / contract opportunities through a
public REST API. Anonymous access is not supported: a free API key
(https://sam.gov/content/webservices) must be set via the ``PRY_SAM_API_KEY``
env var and is sent as the ``api_key`` query parameter. Without a key every
SAM.gov function degrades to ``[]`` / ``{}`` and the fallback sources take
over (never raises).

Sources, in fallback order (a source is only consulted when the previous one
yields nothing, so one provider down never empties the answer):

1. **SAM.gov Opportunities v2** — ``api.sam.gov`` (primary, ``source="sam_gov"``,
   requires ``PRY_SAM_API_KEY``).
2. **grants.gov v2 search API** — ``api.grants.gov/v2/search/opportunities/``
   (``source="grants_gov"``; free, no API key; grant + contract opportunities).
3. **TED (Tenders Electronic Daily, EU)** — ``api.ted.europa.eu/v3/notices/search``
   (``source="ted"``; free, no API key; EU public procurement notices).

Contract
--------
* :func:`search_opportunities` — async, never raises, returns a ``list``
  (``[]`` on failure). Searches procurement opportunities by keyword across
  the SAM.gov → grants.gov → TED fallback chain.
* :func:`search_grants` — async, never raises, returns a ``list`` (``[]`` on
  failure). Searches grant opportunities on grants.gov → TED (no API key
  needed).
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

``source`` is ``"grants_gov"`` for grants.gov records and ``"ted"`` for TED
notices; the non-SAM sources leave ``naics`` / ``set_aside`` as ``None``.

``get_opportunity`` returns the same shape (``{}`` when the notice id does
not exist).

Free-API terms: https://api.sam.gov/opportunities/v2/search — the v2 API
caps page size at 200. grants.gov v2 caps page size at 100; TED v3 at 100.
Backoff: 2 retries, exponential (0.4s -> 1.6s).

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
_GRANTS_GOV_URL = "https://api.grants.gov/v2/search/opportunities/"
_TED_URL = "https://api.ted.europa.eu/v3/notices/search"
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
_KEYLESS_MAX_LIMIT = 100  # grants.gov v2 / TED v3 both cap page size at 100


def _api_key() -> str:
    """Return the configured SAM.gov API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_due(value: str | None) -> str | None:
    """Strip fractional seconds from API due dates (e.g. '2026-01-15 23:59:59.000')."""
    if not value:
        return None
    text = value.strip()
    if "." in text:
        text = text.split(".", 1)[0]
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


def _map_grants_gov(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a grants.gov v2 search hit onto the canonical record."""
    opportunity_id = _as_text(raw.get("opportunityId"))
    url = _as_text(raw.get("opportunityDetailUrl"))
    if not url and opportunity_id:
        url = f"https://www.grants.gov/search-results-detail/{opportunity_id}"
    return {
        "id": opportunity_id,
        "title": _as_text(raw.get("opportunityTitle")),
        "agency": _as_text(raw.get("agencyName")) or _as_text(raw.get("agencyCode")),
        "type": _as_text(raw.get("opportunityCategory")),
        "naics": None,
        "set_aside": None,
        "due_date": _normalize_due(_as_text(raw.get("closeDate"))),
        "url": url,
        "source": "grants_gov",
    }


def _ted_title(raw: Any) -> str | None:
    """Extract a human-readable title from a TED notice's multilingual dict."""
    if isinstance(raw, dict):
        for lang in ("en", "EN", "en-GB"):
            value = raw.get(lang)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in raw.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(raw, str):
        return raw.strip() or None
    return None


def _map_ted(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a TED (EU) v3 notice onto the canonical record."""
    notice_id = _as_text(raw.get("OJS_number"))
    buyer = raw.get("buyer")
    agency = _as_text(buyer.get("name")) if isinstance(buyer, dict) else None
    url = f"https://ted.europa.eu/en/notice/-/detail/{notice_id}" if notice_id else None
    return {
        "id": notice_id,
        "title": _ted_title(raw.get("title"))
        or (f"TED notice {notice_id}" if notice_id else "TED notice"),
        "agency": agency,
        "type": _as_text(raw.get("type")) or "TED Notice",
        "naics": None,
        "set_aside": None,
        "due_date": _normalize_due(_as_text(raw.get("submission_deadline"))),
        "url": url,
        "source": "ted",
    }


async def _fetch_json_post(url: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST JSON ``body`` to ``url`` and return the parsed object, or ``None``.

    Used by the keyless grants.gov and TED search endpoints.
    """

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("procurement POST payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


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
    """Search procurement opportunities by keyword.

    Sources are consulted in fallback order — SAM.gov (needs
    ``PRY_SAM_API_KEY``), grants.gov, then TED (EU) — so one provider being
    down (or unconfigured) never empties the result.

    Args:
        query: Keyword search string (e.g. ``"aircraft maintenance"``).
        limit: Max results to return (1-200; source APIs cap page sizes).

    Returns:
        A list of opportunity records (see module docstring). ``[]`` on
        failure (network error, bad payload). Never raises.
    """
    try:
        return await _search_opportunities(query, limit)
    except Exception:
        logger.exception("gov_procurement_search_crashed", extra={"query": query})
        return []


async def _search_opportunities(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))

    results = await _search_sam(query, clamped)
    if results:
        return results

    results = await _search_grants_gov(query, clamped)
    if results:
        return results

    return await _search_ted(query, clamped)


async def _search_sam(query: str, limit: int) -> list[dict[str, Any]]:
    key = _api_key()
    if not key:
        logger.warning("gov_sam_api_key_missing")
        return []
    params: dict[str, str] = {
        "api_key": key,
        "q": query.strip(),
        "limit": str(limit),
        "page": "0",
    }
    data = await _fetch_opportunities(params)
    if data is None:
        return []
    return [_map_opportunity(raw) for raw in data if isinstance(raw, dict)]


async def _search_grants_gov(query: str, limit: int) -> list[dict[str, Any]]:
    """grants.gov v2 search (keyless POST)."""
    payload = await _fetch_json_post(
        _GRANTS_GOV_URL,
        {
            "keyword": query.strip(),
            "page": 1,
            "limit": max(1, min(limit, _KEYLESS_MAX_LIMIT)),
            "sortBy": "postedDate",
            "sortOrder": "desc",
        },
    )
    if payload is None:
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    opportunities = data.get("opportunities")
    if not isinstance(opportunities, list):
        return []
    return [_map_grants_gov(raw) for raw in opportunities if isinstance(raw, dict)]


async def _search_ted(query: str, limit: int) -> list[dict[str, Any]]:
    """TED (EU) v3 notices search (keyless POST)."""
    payload = await _fetch_json_post(
        _TED_URL,
        {
            "query": query.strip(),
            "limit": max(1, min(limit, _KEYLESS_MAX_LIMIT)),
            "offset": 0,
            "fields": ["OJS_number", "title", "buyer", "type", "submission_deadline"],
        },
    )
    if payload is None:
        return []
    notices = payload.get("notices")
    if not isinstance(notices, list):
        return []
    return [_map_ted(raw) for raw in notices if isinstance(raw, dict)]


async def search_grants(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search grant opportunities on grants.gov (→ TED fallback).

    Unlike :func:`search_opportunities`, this focuses on grant (and
    discretionary) funding: grants.gov is the primary source, and when it
    returns nothing (or fails), the search falls back to the EU's TED
    notices. No API key is required.

    Args:
        query: Keyword search string (e.g. ``"rural broadband"``).
        limit: Max results to return (1-100).

    Returns:
        A list of opportunity records (see module docstring; ``source`` is
        ``"grants_gov"`` or ``"ted"``). ``[]`` on failure. Never raises.
    """
    try:
        return await _search_grants(query, limit)
    except Exception:
        logger.exception("gov_procurement_search_grants_crashed", extra={"query": query})
        return []


async def _search_grants(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    clamped = max(1, min(int(limit), _KEYLESS_MAX_LIMIT))

    results = await _search_grants_gov(query, clamped)
    if results:
        return results

    return await _search_ted(query, clamped)


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
