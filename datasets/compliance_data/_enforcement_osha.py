"""OSHA (IMIS establishment inspections) source for ``compliance_data``.

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
import re
from typing import Any
from urllib.parse import quote

from datasets.compliance_data._enforcement_data import _OSHA_DETAIL_URL, _OSHA_EST_URL
from datasets.compliance_data._enforcement_helpers import (
    _as_text,
    _mmddyyyy_date,
    _sort_records,
    _strip_tags,
)
from datasets.compliance_data._enforcement_transport import _fetch_html

logger = logging.getLogger(__name__)

_OSHA_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_OSHA_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_OSHA_INSPECTION_RE = re.compile(r"\b(\d{7,12}(?:\.\d{3})?)\b")


def _parse_osha_inspections(page: str) -> list[dict[str, Any]]:
    """Signature-parse the OSHA IMIS establishment-search results table.

    Result rows expose inspection number, opening date and establishment
    name (in that order, best-effort). Layout changes degrade to ``[]``.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _OSHA_ROW_RE.findall(page):
        cells = [_strip_tags(cell) or "" for cell in _OSHA_CELL_RE.findall(row)]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3:
            continue
        inspection: str | None = None
        for cell in cells:
            match = _OSHA_INSPECTION_RE.search(cell)
            if match:
                inspection = match.group(1)
                break
        if not inspection or inspection in seen:
            continue
        seen.add(inspection)
        rows.append(
            {
                "id": inspection,
                "title": f"OSHA inspection {inspection}",
                "establishment": cells[-1],
                "date": _mmddyyyy_date(cells[1]) if len(cells) > 1 else None,
                "url": f"{_OSHA_DETAIL_URL}?inspection_number={quote(inspection)}",
            }
        )
    return rows


def _map_osha(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "agency": "osha",
        "id": f"osha:{raw.get('id')}" if raw.get("id") else None,
        "title": _as_text(raw.get("title")),
        "type": "OSHA Inspection",
        "company": _as_text(raw.get("establishment")),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "osha.gov",
    }


async def _fetch_osha(query: str, limit: int) -> list[dict[str, Any]]:
    """OSHA inspection search (keyless HTML scrape of IMIS, best-effort)."""
    params: dict[str, str] = {"Submit": "Search"}
    if query.strip():
        params["establishment"] = query.strip()
    page = await _fetch_html(_OSHA_EST_URL, params)
    if page is None:
        return []
    try:
        rows = _parse_osha_inspections(page)
    except (re.error, ValueError, TypeError):
        logger.warning("compliance_osha_parse_failed", extra={"query": query})
        return []
    needle = query.strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row.get("establishment") or "").lower()
            or needle in str(row.get("id") or "").lower()
        ]
    return _sort_records([_map_osha(row) for row in rows], limit)


async def _get_osha_action(value: str) -> dict[str, Any]:
    page = await _fetch_html(_OSHA_DETAIL_URL, {"inspection_number": value})
    if page is None:
        return {}
    title_match = re.search(r"<title>(.*?)</title>", page, re.S)
    title = _strip_tags(title_match.group(1) if title_match else None)
    est_match = re.search(r"Establishment:\s*(?:</?[^>]+>\s*)*([^<]{2,})", page, re.S)
    establishment = _strip_tags(est_match.group(1) if est_match else None)
    if not title and not establishment:
        return {}
    return {
        "agency": "osha",
        "id": f"osha:{value}",
        "title": title or f"OSHA inspection {value}",
        "summary": None,
        "defendants": [establishment] if establishment else [],
        "penalties": [],
        "url": f"{_OSHA_DETAIL_URL}?inspection_number={quote(value)}",
    }
