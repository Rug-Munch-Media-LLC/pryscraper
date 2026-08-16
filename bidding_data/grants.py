"""Government grant opportunities — free Grants.gov GrantsWS REST API.

Grants.gov publishes federal grant opportunities (including forecasted and
posted) through a public REST API with **no authentication**:

* Search: ``POST https://apply07.grants.gov/grantsws/rest/opportunities/search/``
* Detail: ``POST https://apply07.grants.gov/grantsws/rest/opportunities/``

Contract
--------
* :func:`search_grants` — async, never raises, returns a ``list`` (``[]``
  on failure). Searches grants by keyword ``query``.
* :func:`get_grant` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Fetches one grant by its Grants.gov opp id.

Result shapes
-------------
``search_grants`` returns a list of:

    {
        "id": "351234",
        "title": "Community Development Block Grant",
        "agency": "HUD",
        "funding_type": "Discretionary",
        "open_date": "2026-01-01 00:00:00",
        "close_date": "2026-03-01 00:00:00",
        "amount": "750000",
        "eligible": None,
        "url": "https://www.grants.gov/search-results-detail/ABC-26-001",
        "source": "grants_gov",
    }

``get_grant`` returns the same record enriched with ``description``,
``contacts`` and ``attachments`` (``{}`` when the opp id does not exist).

Free-API terms: Grants.gov GrantsWS is free and requires no API key. The
search endpoint accepts up to 100 rows per request. Backoff: 2 retries,
exponential (0.4s -> 1.6s) for the HTTPError retryable family.

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
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
_DETAIL_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-bidding/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}
_MAX_ROWS = 100  # GrantsWS search caps rows per request at 100


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _grant_url(opp_number: str | None, opp_id: str | None) -> str | None:
    """Best-effort grants.gov detail URL for an opportunity."""
    if opp_number:
        return f"https://www.grants.gov/search-results-detail/{opp_number}"
    if opp_id:
        return f"https://www.grants.gov/search-results-detail/{opp_id}"
    return None


def _map_grant(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Grants.gov search result onto the canonical record."""
    opp_id = _as_text(raw.get("oppId")) or _as_text(raw.get("id"))
    opp_number = _as_text(raw.get("oppNumber"))
    return {
        "id": opp_id,
        "title": _as_text(raw.get("opportunityTitle")),
        "agency": _as_text(raw.get("agency")) or _as_text(raw.get("agencyCode")),
        "funding_type": _as_text(raw.get("opportunityCategoryExplanation"))
        or _as_text(raw.get("fundingInstrument")),
        "open_date": _as_text(raw.get("openDate")),
        "close_date": _as_text(raw.get("closeDate")),
        "amount": _as_text(raw.get("awardCeiling"))
        or _as_text(raw.get("estimatedTotalProgramFunding")),
        "eligible": _as_text(raw.get("applicantEligibility")),
        "url": _grant_url(opp_number, opp_id),
        "source": "grants_gov",
    }


async def _fetch_post_json(url: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST JSON ``body`` to ``url`` and return the parsed object or ``None``."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("grants.gov payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _sort_by_close_date(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sort merged records by close date ascending (soonest first, None last)."""
    records.sort(key=lambda r: (r.get("close_date") is None, str(r.get("close_date") or "")))
    return records[:limit]


# ── Public API ─────────────────────────────────────────────────────────
async def search_grants(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search federal grant opportunities by keyword.

    Args:
        query: Keyword search string (e.g. ``"community development"``).
        limit: Max results to return (1-100; GrantsWS caps rows at 100).

    Returns:
        A list of grant records (see module docstring), sorted by close
        date ascending (soonest first). ``[]`` on failure. Never raises.
    """
    try:
        return await _search_grants(query, limit)
    except Exception:
        logger.exception("bidding_grants_search_crashed", extra={"query": query})
        return []


async def _search_grants(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    rows = max(1, min(int(limit), _MAX_ROWS))
    body: dict[str, Any] = {
        "searchTerm": query.strip(),
        "sortBy": "closeDate|asc",
        "rows": rows,
        "startRecordNum": 0,
        "oppStatuses": "forecasted|posted",
    }
    payload = await _fetch_post_json(_SEARCH_URL, body)
    if payload is None:
        return []
    results = payload.get("oppSearchResults")
    if not isinstance(results, list):
        return []
    records = [
        record
        for raw in results
        if isinstance(raw, dict) and (record := _map_grant(raw)) is not None and record["id"]
    ]
    return _sort_by_close_date(records, rows)


async def get_grant(grant_id: str) -> dict[str, Any]:
    """Fetch one grant by its Grants.gov opp id.

    Args:
        grant_id: Grants.gov opportunity id (int or numeric string).

    Returns:
        Grant detail record (see module docstring) or ``{}`` on failure
        (unknown id, malformed payload, network error). Never raises.
    """
    try:
        return await _get_grant(grant_id)
    except Exception:
        logger.exception("bidding_grants_get_crashed", extra={"grant_id": grant_id})
        return {}


async def _get_grant(grant_id: str) -> dict[str, Any]:
    gid = str(grant_id or "").strip()
    if not gid:
        return {}
    body: dict[str, Any] = {"oppId": gid}
    payload = await _fetch_post_json(_DETAIL_URL, body)
    if payload is None:
        return {}
    detail = payload.get("oppDetail")
    if not isinstance(detail, dict):
        return {}
    record = _map_grant(detail)
    raw_docs = detail.get("documents")
    attachments: list[dict[str, Any]] = []
    if isinstance(raw_docs, list):
        attachments = [
            {
                "title": _as_text(doc.get("title") or doc.get("fileName"))
                if isinstance(doc, dict)
                else None,
                "url": _as_text(doc.get("url") or doc.get("fileLocation"))
                if isinstance(doc, dict)
                else None,
            }
            for doc in raw_docs
            if isinstance(doc, dict) and (doc.get("url") or doc.get("title") or doc.get("fileName"))
        ]
    contacts: dict[str, Any] | None = None
    raw_contact = detail.get("agencyContact")
    if isinstance(raw_contact, dict):
        name = " ".join(
            part
            for part in (
                _as_text(raw_contact.get("firstName")),
                _as_text(raw_contact.get("lastName")),
            )
            if part
        )
        contacts = {
            "name": name or None,
            "email": _as_text(raw_contact.get("email")),
            "phone": _as_text(raw_contact.get("phone")),
        }
    return {
        **record,
        "description": _as_text(detail.get("description"))
        or _as_text(detail.get("opportunityDescription")),
        "contacts": contacts,
        "attachments": attachments,
    }
