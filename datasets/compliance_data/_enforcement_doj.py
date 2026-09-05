"""DOJ (press releases / actions API) source for ``compliance_data.enforcement``.

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

from datasets.compliance_data._enforcement_data import _DOJ_API_URL, _MAX_LIMIT
from datasets.compliance_data._enforcement_helpers import _as_text, _normalize_date, _sort_records
from datasets.compliance_data._enforcement_transport import _fetch_json


def _doj_slug(url: str | None) -> str | None:
    """Last path segment of a DOJ press-release URL (used as a stable id)."""
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _map_doj(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a DOJ press-release API result onto the canonical search record."""
    url = _as_text(raw.get("url"))
    return {
        "agency": "doj",
        "id": f"doj:{_doj_slug(url)}" if url else None,
        "title": _as_text(raw.get("title")),
        "type": _as_text(raw.get("type")) or "DOJ Press Release",
        "company": None,
        "date": _normalize_date(_as_text(raw.get("published_at"))),
        "penalty_amount": None,
        "url": url,
        "source": "justice.gov",
    }


async def _fetch_doj(query: str, limit: int) -> list[dict[str, Any]]:
    """DOJ press-release / action search (free JSON API, no key)."""
    params: dict[str, str] = {
        "page": "1",
        "per_page": str(max(1, min(limit, _MAX_LIMIT))),
        "fields": "title,url,published_at,agency,type",
    }
    if query.strip():
        params["query"] = query.strip()
    payload = await _fetch_json(_DOJ_API_URL, params)
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return _sort_records([_map_doj(raw) for raw in results if isinstance(raw, dict)], limit)


async def _get_doj_action(value: str) -> dict[str, Any]:
    records = await _fetch_doj(value, 1)
    for record in records:
        rid = str(record.get("id") or "")
        if rid == f"doj:{value}" or value in str(record.get("url") or ""):
            return {
                "agency": "doj",
                "id": rid,
                "title": record["title"],
                "summary": None,
                "defendants": [],
                "penalties": [],
                "url": record["url"],
            }
    return {}
