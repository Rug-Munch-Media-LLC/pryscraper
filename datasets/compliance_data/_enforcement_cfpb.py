"""CFPB (consumer complaints API) source for ``compliance_data.enforcement``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from datasets.compliance_data._enforcement_data import _CFPB_SEARCH_URL
from datasets.compliance_data._enforcement_helpers import _as_text, _normalize_date
from datasets.compliance_data._enforcement_transport import _fetch_json


def _map_cfpb(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    complaint_id = _as_text(source.get("complaint_id"))
    product = _as_text(source.get("product"))
    issue = _as_text(source.get("issue"))
    title = " / ".join(part for part in (product, issue) if part) or "Consumer complaint"
    company = _as_text(source.get("company"))
    return {
        "agency": "cfpb",
        "id": f"cfpb:{complaint_id}" if complaint_id else None,
        "title": title,
        "type": product or "CFPB Complaint",
        "company": company,
        "date": _normalize_date(_as_text(source.get("date_received"))),
        "penalty_amount": None,
        "url": (
            f"https://www.consumerfinance.gov/data-research/consumer-complaints/search/"
            f"?q={quote(complaint_id)}"
            if complaint_id
            else None
        ),
        "source": "cfpb",
    }


def _cfpb_detail(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    complaint_id = _as_text(source.get("complaint_id"))
    product = _as_text(source.get("product"))
    issue = _as_text(source.get("issue"))
    title = " / ".join(part for part in (product, issue) if part) or "Consumer complaint"
    company = _as_text(source.get("company"))
    summary = _as_text(source.get("consumer_complaint_narrative")) or _as_text(
        source.get("company_response_to_consumer")
    )
    return {
        "agency": "cfpb",
        "id": f"cfpb:{complaint_id}" if complaint_id else None,
        "title": title,
        "summary": summary,
        "defendants": [company] if company else [],
        "penalties": [],
        "url": (
            f"https://www.consumerfinance.gov/data-research/consumer-complaints/search/"
            f"?q={quote(complaint_id)}"
            if complaint_id
            else None
        ),
    }


async def _cfpb_hits(params: dict[str, str]) -> list[dict[str, Any]]:
    payload = await _fetch_json(_CFPB_SEARCH_URL, params)
    if payload is None:
        return []
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        return []
    items = hits.get("hits")
    if not isinstance(items, list):
        return []
    return [hit for hit in items if isinstance(hit, dict)]


async def _fetch_cfpb(query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, str] = {"size": str(limit)}
    if query.strip():
        params["search_term"] = query.strip()
    hits = await _cfpb_hits(params)
    return [_map_cfpb(hit) for hit in hits]


async def _fetch_cfpb_company(company: str, limit: int) -> list[dict[str, Any]]:
    """Company screening: exact ``company`` filter, full-text fallback."""
    params: dict[str, str] = {"size": str(limit), "company": company}
    hits = await _cfpb_hits(params)
    if not hits and company.strip():
        params = {"size": str(limit), "search_term": company.strip()}
        hits = await _cfpb_hits(params)
    return [_map_cfpb(hit) for hit in hits]


async def _get_cfpb_action(value: str) -> dict[str, Any]:
    hits = await _cfpb_hits({"size": "1", "search_term": value})
    for hit in hits:
        raw_source = hit.get("_source")
        if isinstance(raw_source, dict):
            source: dict[str, Any] = raw_source
        else:
            source = hit
        if _as_text(source.get("complaint_id")) == value:
            return _cfpb_detail(hit)
    return {}
