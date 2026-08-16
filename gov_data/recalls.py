"""Product recalls — CPSC Open Data API + FDA openFDA enforcement reports.

Two free, no-auth public APIs are aggregated here:

* **CPSC** (U.S. Consumer Product Safety Commission) — ``api.cpsc.gov``
  open data API. Consumer-product recalls with full-text ``search``.
* **FDA** (Food & Drug Administration) — ``api.fda.gov`` openFDA
  ``enforcement`` endpoints (food, device, drug). Recalls / market
  withdrawals with ``classification`` (Class I/II/III severity).

Contract
--------
* :func:`search_recalls` — async, never raises, returns a ``list`` (``[]``
  on failure). ``agency`` is ``"all"`` (default), ``"cpsc"``, or ``"fda"``;
  ``"all"`` merges both sources, newest first.
* :func:`get_recall` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Accepts the prefixed ids returned by :func:`search_recalls`
  (``cpsc:<cpscId>`` / ``fda:<recall_number>``) or a bare numeric id
  (treated as CPSC).

Result shapes
-------------
``search_recalls`` returns a list of:

    {
        "id": "cpsc:12345",
        "agency": "cpsc",
        "title": "Children's Hooded Sweatshirts Recalled ...",
        "product": "Children's hooded sweatshirts",
        "reason": "Drawstrings can become entangled ...",
        "date": "2023-01-01",
        "severity": None,
        "url": "https://www.cpsc.gov/Recalls/2023/Recall-12345",
        "source": "cpsc",
    }

FDA records use ``id="fda:<recall_number>"``, ``agency="fda"``, and a
``severity`` of ``"Class I"`` / ``"Class II"`` / ``"Class III"``.

Free-API terms: https://api.cpsc.gov and https://open.fda.gov/apis/
(enforcement endpoints are rate-limited; no key required). Backoff:
2 retries, exponential (0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_CPSC_BASE = "https://api.cpsc.gov/cpsc/v1/recalls"
_FDA_ENDPOINTS: tuple[str, ...] = (
    "https://api.fda.gov/food/enforcement.json",
    "https://api.fda.gov/device/enforcement.json",
    "https://api.fda.gov/drug/enforcement.json",
)
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

_MAX_LIMIT = 100  # both CPSC and openFDA cap page size at 100
_VALID_AGENCIES = {"all", "cpsc", "fda"}


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_fda_date(value: str | None) -> str | None:
    """Normalize an openFDA YYYYMMDD date to YYYY-MM-DD (or passthrough)."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return value


def _fda_recall_url(endpoint: str, recall_number: str | None) -> str | None:
    """Build a deep-linkable openFDA query URL for one recall number."""
    if not recall_number:
        return None
    query = quote(f'recall_number:"{recall_number}"', safe=":")
    return f"{endpoint}?search={query}"


# ── Mapping ────────────────────────────────────────────────────────────
def _map_cpsc(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CPSC Open Data recall object onto the canonical record."""
    cpsc_id = _as_text(raw.get("cpscId"))
    url = _as_text(raw.get("url"))
    if not url and cpsc_id:
        year = _as_text(raw.get("recallDate"))
        year = year[:4] if year and len(year) >= 4 else ""
        url = f"https://www.cpsc.gov/Recalls/{year}/Recall-{cpsc_id}" if year else None
    return {
        "id": f"cpsc:{cpsc_id}" if cpsc_id else None,
        "agency": "cpsc",
        "title": _as_text(raw.get("title")),
        "product": _as_text(raw.get("nameOfProduct")),
        "reason": _as_text(raw.get("hazards")) or _as_text(raw.get("description")),
        "date": _as_text(raw.get("recallDate")),
        "severity": None,  # CPSC does not publish class I/II/III severity
        "url": url,
        "source": "cpsc",
    }


def _map_fda(raw: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Map an openFDA enforcement object onto the canonical record."""
    recall_number = _as_text(raw.get("recall_number"))
    product = _as_text(raw.get("product_description"))
    firm = _as_text(raw.get("recalling_firm"))
    title = product or (f"Recall by {firm}" if firm else None)
    return {
        "id": f"fda:{recall_number}" if recall_number else None,
        "agency": "fda",
        "title": title,
        "product": product,
        "reason": _as_text(raw.get("reason_for_recall")),
        "date": _normalize_fda_date(_as_text(raw.get("recall_initiation_date"))),
        "severity": _as_text(raw.get("classification")),
        "url": _fda_recall_url(endpoint, recall_number),
        "source": "openfda",
    }


# ── Fetching ───────────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("recall API payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_cpsc(query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, str] = {"limit": str(limit), "skip": "0"}
    if query.strip():
        params["search"] = query.strip()
    payload = await _fetch_json(_CPSC_BASE, params)
    if payload is None:
        return []
    recalls = payload.get("recalls")
    if not isinstance(recalls, list):
        return []
    return [_map_cpsc(raw) for raw in recalls if isinstance(raw, dict)]


async def _fetch_fda(query: str, limit: int) -> list[dict[str, Any]]:
    async def _one(endpoint: str) -> list[dict[str, Any]]:
        params: dict[str, str] = {"limit": str(limit)}
        if query.strip():
            params["search"] = query.strip()
        payload = await _fetch_json(endpoint, params)
        if payload is None:
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [_map_fda(raw, endpoint) for raw in results if isinstance(raw, dict)]

    chunks = await asyncio.gather(*(_one(endpoint) for endpoint in _FDA_ENDPOINTS))
    records = [record for chunk in chunks for record in chunk]
    records.sort(key=lambda record: str(record.get("date") or ""), reverse=True)
    return records[:limit]


def _sort_records(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    records.sort(key=lambda record: str(record.get("date") or ""), reverse=True)
    return records[:limit]


# ── Public API ─────────────────────────────────────────────────────────
async def search_recalls(query: str, agency: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Search product recalls across CPSC and/or FDA.

    Args:
        query: Keyword search string (e.g. ``"children's sweatshirt"``).
        agency: ``"all"`` (default, both sources merged newest-first),
            ``"cpsc"``, or ``"fda"``.
        limit: Max results to return (1-100).

    Returns:
        A list of recall records (see module docstring). ``[]`` on failure
        or invalid agency. Never raises.
    """
    try:
        return await _search_recalls(query, agency, limit)
    except Exception:
        logger.exception("gov_recalls_search_crashed", extra={"query": query, "agency": agency})
        return []


async def _search_recalls(query: str, agency: str, limit: int) -> list[dict[str, Any]]:
    normalized = str(agency).strip().lower()
    if normalized not in _VALID_AGENCIES:
        logger.warning("gov_recalls_invalid_agency", extra={"agency": agency})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    if normalized == "cpsc":
        return await _fetch_cpsc(query, clamped)
    if normalized == "fda":
        return await _fetch_fda(query, clamped)
    merged = await _fetch_cpsc(query, clamped)
    merged.extend(await _fetch_fda(query, clamped))
    return _sort_records(merged, clamped)


async def get_recall(recall_id: str) -> dict[str, Any]:
    """Fetch one recall by its prefixed id.

    Args:
        recall_id: ``cpsc:<cpscId>``, ``fda:<recall_number>``, or a bare
            numeric id (treated as CPSC).

    Returns:
        Recall record (see module docstring) or ``{}`` on failure
        (unknown id, network error). Never raises.
    """
    try:
        return await _get_recall(recall_id)
    except Exception:
        logger.exception("gov_recalls_get_crashed", extra={"recall_id": recall_id})
        return {}


async def _get_recall(recall_id: str) -> dict[str, Any]:
    if not recall_id or not str(recall_id).strip():
        return {}
    rid = str(recall_id).strip()
    agency, _, value = rid.partition(":")
    if not value:
        # Bare numeric id → CPSC (e.g. "12345" instead of "cpsc:12345").
        value = rid
        agency = "cpsc"
    if agency == "cpsc":
        return await _get_cpsc(value)
    if agency == "fda":
        return await _get_fda(value)
    logger.warning("gov_recalls_unknown_id", extra={"recall_id": recall_id})
    return {}


async def _get_cpsc(value: str) -> dict[str, Any]:
    payload = await _fetch_json(_CPSC_BASE, {"search": value, "limit": "100", "skip": "0"})
    if payload is None:
        return {}
    recalls = payload.get("recalls")
    if not isinstance(recalls, list):
        return {}
    for raw in recalls:
        if isinstance(raw, dict) and _as_text(raw.get("cpscId")) == value:
            return _map_cpsc(raw)
    return {}


async def _get_fda(value: str) -> dict[str, Any]:
    async def _one(endpoint: str) -> dict[str, Any]:
        payload = await _fetch_json(endpoint, {"search": f'recall_number:"{value}"', "limit": "1"})
        if payload is None:
            return {}
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return _map_fda(results[0], endpoint)
        return {}

    for record in await asyncio.gather(*(_one(endpoint) for endpoint in _FDA_ENDPOINTS)):
        if record:
            return record
    return {}
