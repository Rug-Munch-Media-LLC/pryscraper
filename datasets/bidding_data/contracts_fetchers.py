"""Source fetchers: SAM.gov, TED (EU), NY State Contract Reporter, FedConnect.

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

from datasets.bidding_data.contracts_common import (
    _API_KEY_ENV,
    _FEDCONNECT_BASE,
    _NY_BASE,
    _NY_DETAIL_BASE,
    _SAM_BASE,
    _SAM_MAX_LIMIT,
    _TED_BASE,
    _TED_DETAIL_BASE,
    _as_text,
    _canonical_type,
    _fetch_json,
    _fetch_text,
    _gov_procurement,
)
from datasets.bidding_data.contracts_parsers import (
    _FEDCONNECT_LINK_RE,
    _FEDCONNECT_TITLE_RE,
    _fedconnect_map,
    _ny_map,
    _sam_map,
    _ted_map,
)

logger = logging.getLogger(__name__)


# ── SAM.gov ────────────────────────────────────────────────────────────
def _sam_api_key() -> str:
    """Return the configured SAM.gov API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


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
