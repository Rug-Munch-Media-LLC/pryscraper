"""FDA (openFDA enforcement) source for ``compliance_data.enforcement``.

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
from typing import Any
from urllib.parse import quote

from datasets.compliance_data._enforcement_data import _FDA_ENDPOINTS
from datasets.compliance_data._enforcement_helpers import (
    _as_text,
    _normalize_date,
    _sort_records,
)
from datasets.compliance_data._enforcement_transport import _fetch_json


def _fda_url(endpoint: str, recall_number: str | None) -> str | None:
    """Build a deep-linkable openFDA query URL for one recall number."""
    if not recall_number:
        return None
    query = quote(f'recall_number:"{recall_number}"', safe=":")
    return f"{endpoint}?search={query}"


def _map_fda(raw: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Map an openFDA enforcement object onto the canonical search record."""
    recall_number = _as_text(raw.get("recall_number"))
    firm = _as_text(raw.get("recalling_firm"))
    product = _as_text(raw.get("product_description"))
    title = product or (f"FDA enforcement action - {firm}" if firm else "FDA enforcement action")
    return {
        "agency": "fda",
        "id": f"fda:{recall_number}" if recall_number else None,
        "title": title,
        "type": _as_text(raw.get("classification")) or "FDA Enforcement",
        "company": firm,
        "date": _normalize_date(_as_text(raw.get("recall_initiation_date"))),
        "penalty_amount": None,
        "url": _fda_url(endpoint, recall_number),
        "source": "openfda",
    }


def _fda_detail(raw: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Map an openFDA enforcement object onto the action-detail shape."""
    recall_number = _as_text(raw.get("recall_number"))
    firm = _as_text(raw.get("recalling_firm"))
    classification = _as_text(raw.get("classification"))
    return {
        "agency": "fda",
        "id": f"fda:{recall_number}" if recall_number else None,
        "title": _as_text(raw.get("product_description"))
        or (f"FDA enforcement action - {firm}" if firm else "FDA enforcement action"),
        "summary": _as_text(raw.get("reason_for_recall")),
        "defendants": [firm] if firm else [],
        "penalties": [{"type": classification or "market withdrawal", "amount": None}],
        "url": _fda_url(endpoint, recall_number),
    }


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
    return _sort_records([record for chunk in chunks for record in chunk], limit)


async def _get_fda_action(value: str) -> dict[str, Any]:
    async def _one(endpoint: str) -> dict[str, Any]:
        payload = await _fetch_json(endpoint, {"search": f'recall_number:"{value}"', "limit": "1"})
        if payload is None:
            return {}
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return _fda_detail(results[0], endpoint)
        return {}

    for record in await asyncio.gather(*(_one(endpoint) for endpoint in _FDA_ENDPOINTS)):
        if record:
            return record
    return {}
