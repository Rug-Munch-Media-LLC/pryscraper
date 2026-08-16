"""Government contract bidding data — solicitations + awards, multi-source.

Aggregates free, no-auth (or free-key) sources of public contract
opportunities for the highest-value B2B procurement niche:

* **SAM.gov** — federal solicitations / awards. Reuses
  :mod:`gov_data.procurement` when it is present in this tree (it already
  wraps the free SAM.gov Opportunities API v2); otherwise falls back to the
  same API directly (key ``PRY_SAM_API_KEY``, free at
  https://sam.gov/content/webservices).
* **TED** (EU) — the European Union's Tenders Electronic Daily. Free public
  search API, no auth: https://api.ted.europa.eu/v3/notices/search.
* **NY State Contract Reporter** — one well-documented state portal
  (``nycr.ny.gov``). Public JSON search, no auth. Best-effort.
* **FedConnect** — federal "public opportunities" search. Best-effort HTML
  parse (FedConnect has no documented JSON API; may return ``[]``).

Contract
--------
* :func:`search_contracts` — async, never raises, returns a ``list``
  (``[]`` on failure). Merges all four sources, newest due-date first.
* :func:`get_contract` — async, never raises, returns a ``dict`` (``{}``
  on failure). Fetches one record by its source-prefixed id
  (``sam:`` / ``ted:`` / ``ny:`` / ``fedconnect:``; bare ids default to
  SAM.gov).

Result shapes
-------------
``search_contracts`` returns a list of:

    {
        "id": "sam:3488234",
        "title": "Z--TEST Presolicitation",
        "agency": "DEPT OF THE AIR FORCE",
        "type": "solicitation",          # "solicitation" | "award"
        "notice_type": "Presolicitation",
        "naics": "336411",
        "set_aside": "Total Small Business Set-Aside (FAR 19.5)",
        "due_date": "2026-01-01 12:00:00+00",
        "award_date": None,
        "value": None,
        "url": "https://sam.gov/opp/3488234/view",
        "source": "sam_gov",
    }

``get_contract`` returns a richer detail record (``{}`` when the id does
not exist) with ``description``, ``contacts`` and ``attachments``.

Free-API terms: SAM.gov v2 caps page size at 200; TED and NYSCR are free
public endpoints without documented hard rate limits. Backoff: 2 retries,
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

import asyncio
import logging
import os
import re
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

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
}

# SAM.gov free API key: https://sam.gov/content/webservices
_API_KEY_ENV = "PRY_SAM_API_KEY"
_SAM_BASE = "https://api.sam.gov/opportunities/v2/search"
_SAM_MAX_LIMIT = 200

_TED_BASE = "https://api.ted.europa.eu/v3/notices/search"
_TED_DETAIL_BASE = "https://api.ted.europa.eu/v3/notices"

_NY_BASE = "https://www.nycr.ny.gov/api/contracts/search"
_NY_DETAIL_BASE = "https://www.nycr.ny.gov/api/contracts"

_FEDCONNECT_BASE = "https://www.fedconnect.net/FedConnect/PublicPages/PublicSearch.aspx"

# Module-level reference to gov_data.procurement, resolved lazily so the
# package works even while sibling gov_data modules are still landing.
_gov_data_procurement: Any | None = None


# ── Shared helpers ──────────────────────────────────────────────────────
def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_type(notice_type: str | None) -> str:
    """Map a raw notice type to the canonical ``solicitation``/``award``."""
    if not notice_type:
        return "solicitation"
    lowered = notice_type.lower()
    return "award" if "award" in lowered else "solicitation"


def _sort_by_due_date(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sort merged records by due date ascending (soonest first, None last)."""
    records.sort(key=lambda r: (r.get("due_date") is None, str(r.get("due_date") or "")))
    return records[:limit]


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
            raise ValueError("bidding payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text(url: str, params: dict[str, str] | None = None) -> str | None:
    """GET ``url`` and return the raw response text, or ``None`` on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
        return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


def _gov_procurement() -> Any | None:
    """Return the ``gov_data.procurement`` module, or ``None`` when absent.

    The reference is cached on first resolution so callers (and tests) can
    force the direct SAM.gov path by clearing ``_gov_data_procurement``.
    """
    global _gov_data_procurement
    if _gov_data_procurement is None:
        try:
            import gov_data.procurement as _module  # type: ignore[attr-defined]

            _gov_data_procurement = _module
        except ImportError:  # pragma: no cover — parallel build not landed yet
            _gov_data_procurement = None
    return _gov_data_procurement


# ── SAM.gov ────────────────────────────────────────────────────────────
def _sam_api_key() -> str:
    """Return the configured SAM.gov API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _sam_map(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a SAM.gov Opportunities v2 object onto the canonical record."""
    notice_id = _as_text(raw.get("noticeId"))
    url = _as_text(raw.get("url"))
    if not url and notice_id:
        url = f"https://sam.gov/opp/{notice_id}/view"
    notice_type = _as_text(raw.get("typeOfNotice")) or _as_text(raw.get("noticeType"))
    return {
        "id": f"sam:{notice_id}" if notice_id else None,
        "title": _as_text(raw.get("title")),
        "agency": _as_text(raw.get("agency")),
        "type": _canonical_type(notice_type),
        "notice_type": notice_type,
        "naics": _as_text(raw.get("naicsCode")),
        "set_aside": _as_text(raw.get("setAside"))
        or _as_text(raw.get("typeOfSetAsideDescription")),
        "due_date": _as_text(raw.get("responseDeadLine")) or _as_text(raw.get("responseDate")),
        "award_date": _as_text(raw.get("awardDate")),
        "value": _as_text(raw.get("estimatedValue")),
        "url": url,
        "source": "sam_gov",
    }


async def _sam_direct_records(query: str, limit: int) -> list[dict[str, Any]]:
    """Direct SAM.gov Opportunities v2 fetch (used when gov_data is absent)."""
    key = _sam_api_key()
    if not key:
        logger.warning("bidding_sam_api_key_missing")
        return []
    params: dict[str, str] = {
        "api_key": key,
        "q": query.strip(),
        "limit": str(max(1, min(int(limit), _SAM_MAX_LIMIT))),
        "page": "0",
    }
    payload = await _fetch_json(_SAM_BASE, params)
    if payload is None:
        return []
    data = payload.get("opportunitiesData")
    if not isinstance(data, list):
        return []
    return [_sam_map(raw) for raw in data if isinstance(raw, dict) and _sam_map(raw)["id"]]


async def _sam_records(query: str, limit: int) -> list[dict[str, Any]]:
    """SAM.gov search — reuse gov_data.procurement when present, else direct."""
    try:
        gov = _gov_procurement()
        if gov is not None:
            raw_records = await gov.search_opportunities(query=query, limit=limit)
            return [
                {
                    "id": f"sam:{r['id']}" if r.get("id") else None,
                    "title": r.get("title"),
                    "agency": r.get("agency"),
                    "type": _canonical_type(_as_text(r.get("type"))),
                    "notice_type": r.get("type"),
                    "naics": r.get("naics"),
                    "set_aside": r.get("set_aside"),
                    "due_date": r.get("due_date"),
                    "award_date": None,
                    "value": None,
                    "url": r.get("url"),
                    "source": "sam_gov",
                }
                for r in raw_records
                if isinstance(r, dict) and r.get("id")
            ]
        return await _sam_direct_records(query, limit)
    except Exception:
        logger.exception("bidding_sam_records_crashed", extra={"query": query})
        return []


async def _sam_get(notice_id: str) -> dict[str, Any]:
    """Fetch one SAM.gov opportunity detail (reuse gov_data when present)."""
    try:
        gov = _gov_procurement()
        if gov is not None:
            raw = await gov.get_opportunity(notice_id)
            if not raw:
                return {}
            record = _sam_map(
                {
                    "noticeId": notice_id,
                    "title": raw.get("title"),
                    "agency": raw.get("agency"),
                    "typeOfNotice": raw.get("type"),
                    "naicsCode": raw.get("naics"),
                    "setAside": raw.get("set_aside"),
                    "responseDeadLine": raw.get("due_date"),
                    "url": raw.get("url"),
                }
            )
            return {
                **record,
                "description": raw.get("description"),
                "contacts": None,
                "attachments": [],
            }
        key = _sam_api_key()
        if not key:
            logger.warning("bidding_sam_api_key_missing")
            return {}
        params: dict[str, str] = {
            "api_key": key,
            "noticeId": notice_id.strip(),
            "limit": "1",
            "page": "0",
        }
        payload = await _fetch_json(_SAM_BASE, params)
        if payload is None:
            return {}
        data = payload.get("opportunitiesData")
        if not isinstance(data, list) or not data:
            return {}
        return {
            **_sam_map(data[0]),
            "description": _as_text(data[0].get("description")),
            "contacts": None,
            "attachments": [],
        }
    except Exception:
        logger.exception("bidding_sam_get_crashed", extra={"notice_id": notice_id})
        return {}


# ── TED (EU) ────────────────────────────────────────────────────────────
def _ted_map(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a TED v3 notice search result onto the canonical record."""
    pub = _as_text(raw.get("publicationNumber"))
    if not pub:
        return None
    buyer = raw.get("buyer")
    buyer_name = _as_text(buyer.get("name")) if isinstance(buyer, dict) else None
    notice_type = _as_text(raw.get("noticeType")) or _as_text(raw.get("noticeTypeName"))
    value = raw.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    return {
        "id": f"ted:{pub}",
        "title": _as_text(raw.get("title")) or _as_text(raw.get("noticeTitle")),
        "agency": buyer_name,
        "type": _canonical_type(notice_type),
        "notice_type": notice_type,
        "naics": None,
        "set_aside": None,
        "due_date": _as_text(raw.get("deadlineDate")) or _as_text(raw.get("tenderDeadline")),
        "award_date": _as_text(raw.get("awardDate")),
        "value": _as_text(value),
        "url": f"https://ted.europa.eu/en/notice/-/detail/{pub}",
        "source": "ted",
    }


async def _ted_records(query: str, limit: int) -> list[dict[str, Any]]:
    """TED (EU) notice search — free public API, no auth."""
    try:
        params: dict[str, str] = {
            "query": query.strip(),
            "limit": str(max(1, min(int(limit), 200))),
            "page": "1",
            "sortBy": "publicationDate|desc",
        }
        payload = await _fetch_json(_TED_BASE, params)
        if payload is None:
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [
            record
            for raw in results
            if isinstance(raw, dict) and (record := _ted_map(raw)) is not None
        ]
    except Exception:
        logger.exception("bidding_ted_records_crashed", extra={"query": query})
        return []


async def _ted_get(publication_number: str) -> dict[str, Any]:
    """Fetch one TED notice detail (best-effort via notice endpoint)."""
    try:
        pub = publication_number.strip()
        payload = await _fetch_json(f"{_TED_DETAIL_BASE}/{pub}")
        if payload is None:
            return {}
        mapped = _ted_map(payload) or {}
        raw_docs = payload.get("documents") or payload.get("attachments")
        attachments: list[dict[str, Any]] = []
        if isinstance(raw_docs, list):
            attachments = [
                {
                    "title": _as_text(doc.get("title")) if isinstance(doc, dict) else None,
                    "url": _as_text(doc.get("url") if isinstance(doc, dict) else None),
                }
                for doc in raw_docs
                if isinstance(doc, dict) and (doc.get("url") or doc.get("title"))
            ]
        contacts = payload.get("buyerContact") or payload.get("contactPoint")
        if isinstance(payload.get("buyer"), dict) and not contacts:
            contacts = payload["buyer"].get("contact")
        return {
            **mapped,
            "id": f"ted:{pub}",
            "description": _as_text(payload.get("description"))
            or _as_text(payload.get("noticeDescription")),
            "contacts": contacts if isinstance(contacts, dict) else None,
            "attachments": attachments,
        }
    except Exception:
        logger.exception(
            "bidding_ted_get_crashed", extra={"publication_number": publication_number}
        )
        return {}


# ── NY State Contract Reporter ──────────────────────────────────────────
def _ny_map(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an NYSCR record onto the canonical record."""
    nid = _as_text(raw.get("id"))
    return {
        "id": f"ny:{nid}" if nid else None,
        "title": _as_text(raw.get("title")),
        "agency": _as_text(raw.get("agencyName")) or _as_text(raw.get("agency")),
        "type": "solicitation",
        "notice_type": "Contract Notice",
        "naics": _as_text(raw.get("naicsCode")),
        "set_aside": None,
        "due_date": _as_text(raw.get("dueDate")) or _as_text(raw.get("bidDueDate")),
        "award_date": None,
        "value": _as_text(raw.get("estimatedValue")),
        "url": _as_text(raw.get("url"))
        or (f"https://www.nycr.ny.gov/api/contracts/{nid}" if nid else None),
        "source": "ny_contract_reporter",
    }


async def _ny_records(query: str, limit: int) -> list[dict[str, Any]]:
    """NY State Contract Reporter search — free public JSON, no auth."""
    try:
        params: dict[str, str] = {
            "searchTerm": query.strip(),
            "pageSize": str(max(1, min(int(limit), 200))),
        }
        payload = await _fetch_json(_NY_BASE, params)
        if payload is None:
            return []
        results = payload.get("results") or payload.get("contracts")
        if not isinstance(results, list):
            return []
        return [
            record for raw in results if isinstance(raw, dict) and (record := _ny_map(raw))["id"]
        ]
    except Exception:
        logger.exception("bidding_ny_records_crashed", extra={"query": query})
        return []


async def _ny_get(contract_id: str) -> dict[str, Any]:
    """Fetch one NYSCR contract detail (best-effort)."""
    try:
        cid = contract_id.strip()
        payload = await _fetch_json(f"{_NY_DETAIL_BASE}/{cid}")
        if payload is None:
            return {}
        record = _ny_map(payload)
        raw_docs = payload.get("documents")
        attachments: list[dict[str, Any]] = []
        if isinstance(raw_docs, list):
            attachments = [
                {
                    "title": _as_text(doc.get("title") or doc.get("name"))
                    if isinstance(doc, dict)
                    else None,
                    "url": _as_text(doc.get("url")) if isinstance(doc, dict) else None,
                }
                for doc in raw_docs
                if isinstance(doc, dict) and (doc.get("url") or doc.get("title"))
            ]
        contacts: dict[str, Any] | None = None
        contact_fields = {
            "name": payload.get("contactName"),
            "email": payload.get("contactEmail"),
            "phone": payload.get("contactPhone"),
        }
        if any(contact_fields.values()):
            contacts = {k: _as_text(v) for k, v in contact_fields.items()}
        return {
            **record,
            "description": _as_text(payload.get("description")),
            "contacts": contacts,
            "attachments": attachments,
        }
    except Exception:
        logger.exception("bidding_ny_get_crashed", extra={"contract_id": contract_id})
        return {}


# ── FedConnect (best-effort HTML) ───────────────────────────────────────
_FEDCONNECT_LINK_RE = re.compile(r'PublicSearch\.aspx\?doc=([^"&\s]+)">([^<]+)</a>', re.IGNORECASE)
_FEDCONNECT_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE | re.DOTALL)


def _fedconnect_map(doc: str, title: str) -> dict[str, Any]:
    """Build a canonical record from a FedConnect document link."""
    return {
        "id": f"fedconnect:{doc}",
        "title": title.strip() or f"FedConnect opportunity {doc}",
        "agency": None,
        "type": "solicitation",
        "notice_type": "FedConnect Opportunity",
        "naics": None,
        "set_aside": None,
        "due_date": None,
        "award_date": None,
        "value": None,
        "url": f"{_FEDCONNECT_BASE}?doc={doc}",
        "source": "fedconnect",
    }


async def _fedconnect_records(query: str, limit: int) -> list[dict[str, Any]]:
    """FedConnect public search — best-effort HTML parse, may return []."""
    try:
        params: dict[str, str] = {"SearchType": "1", "SearchText": query.strip()}
        html = await _fetch_text(_FEDCONNECT_BASE, params)
        if not html:
            return []
        matches = _FEDCONNECT_LINK_RE.findall(html)
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc, title in matches:
            if doc in seen:
                continue
            seen.add(doc)
            records.append(_fedconnect_map(doc, title))
            if len(records) >= limit:
                break
        return records
    except Exception:
        logger.exception("bidding_fedconnect_records_crashed", extra={"query": query})
        return []


async def _fedconnect_get(doc: str) -> dict[str, Any]:
    """Fetch one FedConnect document detail (best-effort HTML title parse)."""
    try:
        params: dict[str, str] = {"doc": doc.strip()}
        html = await _fetch_text(_FEDCONNECT_BASE, params)
        if not html:
            return {}
        title_match = _FEDCONNECT_TITLE_RE.search(html)
        title = title_match.group(1).strip() if title_match else None
        return {
            **_fedconnect_map(doc.strip(), title or ""),
            "description": None,
            "contacts": None,
            "attachments": [],
        }
    except Exception:
        logger.exception("bidding_fedconnect_get_crashed", extra={"doc": doc})
        return {}


# ── Public API ─────────────────────────────────────────────────────────
async def search_contracts(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search contract solicitations + awards across all free sources.

    Args:
        query: Keyword search string (e.g. ``"aircraft maintenance"``).
        limit: Max results to return (1-200; each source is capped at 200).

    Returns:
        A list of contract records (see module docstring), merged across
        SAM.gov, TED, NY Contract Reporter and FedConnect, sorted by due
        date ascending (soonest first; records without a due date last).
        ``[]`` on failure. Never raises.
    """
    try:
        return await _search_contracts(query, limit)
    except Exception:
        logger.exception("bidding_contracts_search_crashed", extra={"query": query})
        return []


async def _search_contracts(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    capped = max(1, min(int(limit), 200))
    chunks = await asyncio.gather(
        _sam_records(query, capped),
        _ted_records(query, capped),
        _ny_records(query, capped),
        _fedconnect_records(query, capped),
    )
    records = [record for chunk in chunks for record in chunk if isinstance(record, dict)]
    return _sort_by_due_date(records, capped)


async def get_contract(contract_id: str) -> dict[str, Any]:
    """Fetch one contract by its source-prefixed id.

    Args:
        contract_id: e.g. ``"sam:3488234"``, ``"ted:123456-2026"``,
            ``"ny:42"``, ``"fedconnect:FA1234"``. Bare ids default to
            SAM.gov.

    Returns:
        Contract detail record (see module docstring) or ``{}`` on failure
        (unknown id, source error, network error). Never raises.
    """
    try:
        return await _get_contract(contract_id)
    except Exception:
        logger.exception("bidding_contracts_get_crashed", extra={"contract_id": contract_id})
        return {}


async def _get_contract(contract_id: str) -> dict[str, Any]:
    cid = str(contract_id or "").strip()
    if not cid:
        return {}
    prefix, sep, rest = cid.partition(":")
    if sep:
        if prefix == "sam":
            return await _sam_get(rest)
        if prefix == "ted":
            return await _ted_get(rest)
        if prefix == "ny":
            return await _ny_get(rest)
        if prefix == "fedconnect":
            return await _fedconnect_get(rest)
        logger.warning("bidding_contracts_unknown_prefix", extra={"prefix": prefix})
        return {}
    # Bare numeric ids default to SAM.gov (largest federal source).
    return await _sam_get(cid)
