"""U.S. federal/state docket search — free CourtListener REST API v4.

CourtListener (free.law) publishes the RECAP / PACER docket database through
a public REST API. Anonymous access is rate-limited; a free API token can be
set via the ``PRY_COURTLISTENER_API_KEY`` env var and is sent as
``Authorization: Token <key>``. Without a token the API currently returns
401, which degrades every function to ``{}`` / ``[]`` (never raises) — the
module still works fully when a token is configured.

Contract
--------
* :func:`search_dockets` — async, never raises, returns a ``list`` (``[]``
  on failure). Searches dockets by full-text ``query``.
* :func:`get_docket` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Fetches one docket by its CourtListener integer id.

Result shapes
-------------
``search_dockets`` returns a list of:

    {
        "id": 123456,
        "case_name": "United States v. Example Corp.",
        "docket_number": "1:22-cv-00001",
        "court": "dcd",                    # CourtListener court code
        "date_filed": "2022-01-15",
        "date_terminated": None,
        "nature_of_suit": "Contract",
        "cause": None,
        "url": "https://www.courtlistener.com/docket/123456/",
        "source": "courtlistener",
    }

``get_docket`` returns the same fields plus ``description``,
``jury_demand``, ``jurisdiction_type``, ``date_argued``,
``date_reargued``, ``date_last_filing``, ``appeal_from`` and ``panel``.

Free-API terms: https://www.courtlistener.com/api/rest/v4/ — identify
yourself with a descriptive User-Agent. Backoff: 2 retries, exponential
(0.4s -> 1.6s).

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

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}

# Optional free token: https://www.courtlistener.com/accounts/register/
_API_KEY_ENV = "PRY_COURTLISTENER_API_KEY"


def _headers() -> dict[str, str]:
    """Base request headers plus the CourtListener token when configured."""
    token = os.environ.get(_API_KEY_ENV, "").strip()
    if token:
        return {**_HEADERS, "Authorization": f"Token {token}"}
    return dict(_HEADERS)


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    """Coerce a JSON value to int/None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_docket(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CourtListener v4 docket object onto the canonical record."""
    docket_id = _as_int(raw.get("id"))
    url = f"https://www.courtlistener.com/docket/{docket_id}/" if docket_id else None
    return {
        "id": docket_id,
        "case_name": _as_text(raw.get("case_name")),
        "docket_number": _as_text(raw.get("docket_number")),
        "court": _as_text(raw.get("court")),
        "date_filed": _as_text(raw.get("date_filed")),
        "date_terminated": _as_text(raw.get("date_terminated")),
        "nature_of_suit": _as_text(raw.get("nature_of_suit")),
        "cause": _as_text(raw.get("cause")),
        "url": url,
        "source": "courtlistener",
    }


def _map_docket_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a full CourtListener v4 docket object (detail view) — superset of :func:`_map_docket`."""
    record = _map_docket(raw)
    record.update(
        {
            "description": _as_text(raw.get("description")),
            "jury_demand": _as_text(raw.get("jury_demand")),
            "jurisdiction_type": _as_text(raw.get("jurisdiction_type")),
            "date_argued": _as_text(raw.get("date_argued")),
            "date_reargued": _as_text(raw.get("date_reargued")),
            "date_last_filing": _as_text(raw.get("date_last_filing")),
            "appeal_from": _as_text(raw.get("appeal_from")),
            "panel": _as_text(raw.get("panel")),
        }
    )
    return record


async def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("courtlistener payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def search_dockets(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search CourtListener dockets by full-text query.

    Args:
        query: Full-text search string (e.g. ``"bitcoin ethereum fraud"``).
        limit: Max results to return (1-100; API caps page size at 100).

    Returns:
        A list of docket records (see module docstring). ``[]`` on failure
        (401 without a token, network error, bad payload). Never raises.
    """
    try:
        return await _search_dockets(query, limit)
    except Exception:
        logger.exception("legal_dockets_search_crashed", extra={"query": query})
        return []


async def _search_dockets(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    payload = await _fetch_json(
        f"{_BASE_URL}/dockets/",
        {"q": query.strip(), "page_size": max(1, min(int(limit), 100))},
    )
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [_map_docket(raw) for raw in results if isinstance(raw, dict)]


async def get_docket(docket_id: int | str) -> dict[str, Any]:
    """Fetch one CourtListener docket by its integer id.

    Args:
        docket_id: CourtListener docket id (int or numeric string).

    Returns:
        Full docket record (see module docstring) or ``{}`` on failure
        (unknown id -> 404, network error, 401 without token). Never raises.
    """
    try:
        return await _get_docket(docket_id)
    except Exception:
        logger.exception("legal_dockets_get_crashed", extra={"docket_id": docket_id})
        return {}


async def _get_docket(docket_id: int | str) -> dict[str, Any]:
    try:
        numeric = int(docket_id)
    except (TypeError, ValueError):
        logger.warning("legal_dockets_invalid_id", extra={"docket_id": docket_id})
        return {}
    payload = await _fetch_json(f"{_BASE_URL}/dockets/{numeric}/")
    if payload is None:
        return {}
    return _map_docket_detail(payload)
