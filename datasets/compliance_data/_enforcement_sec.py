"""SEC (EDGAR full-text + AAER admin proceedings) source for ``compliance_data``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from datasets.compliance_data._enforcement_data import _SEC_ADMIN_URL, _SEC_FTS_URL
from datasets.compliance_data._enforcement_helpers import (
    _as_text,
    _dedupe_records,
    _normalize_date,
    _sort_records,
    _strip_tags,
)
from datasets.compliance_data._enforcement_transport import _fetch_html, _fetch_json


def _parse_sec_admin(page: str) -> list[dict[str, Any]]:
    """Parse the SEC administrative-proceedings listing into raw rows."""
    rows: list[dict[str, Any]] = []
    for chunk in page.split('<tr class="pr-list-page-row">')[1:]:
        time_match = re.search(r'<time datetime="([^"]+)"', chunk)
        respondent_match = re.search(
            r"class=['\"]release-view__respondents['\"]><a href=['\"]([^'\"]+)['\"]>([^<]+)</a>",
            chunk,
        )
        release_match = re.search(r'view-table_subfield_value">([^<]+)<', chunk)
        url = _as_text(respondent_match.group(1) if respondent_match else None)
        title = _strip_tags(respondent_match.group(2) if respondent_match else None)
        release_text = _as_text(release_match.group(1) if release_match else None)
        if not title and not release_text:
            continue
        stem = None
        if url:
            stem_match = re.search(r"/([^/]+)\.pdf$", url)
            stem = stem_match.group(1) if stem_match else None
        rows.append(
            {
                "id": stem or release_text,
                "title": title or f"SEC enforcement action ({release_text or 'unknown'})",
                "release": release_text,
                "date": _normalize_date(_as_text(time_match.group(1) if time_match else None)),
                "url": url,
            }
        )
    return rows


def _map_sec_admin(raw: dict[str, Any]) -> dict[str, Any]:
    release = _as_text(raw.get("release")) or ""
    action_type = "AAER" if "AAER" in release.upper() else "Admin Proceeding"
    return {
        "agency": "sec",
        "id": f"sec:{raw.get('id')}" if raw.get("id") else None,
        "title": _as_text(raw.get("title")),
        "type": action_type,
        "company": _as_text(raw.get("title")),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "sec.gov",
    }


def _map_sec_edgar(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    doc_id = _as_text(hit.get("_id"))
    form = _as_text(source.get("form")) or _as_text(source.get("file_type"))
    date = _normalize_date(_as_text(source.get("file_date"))) or _normalize_date(
        _as_text(source.get("display_date"))
    )
    return {
        "agency": "sec",
        "id": f"sec:{doc_id}" if doc_id else None,
        "title": form or "SEC filing",
        "type": form or "EDGAR Filing",
        "company": None,
        "date": date,
        "penalty_amount": None,
        "url": f"{_SEC_FTS_URL}?q={quote(doc_id)}" if doc_id else None,
        "source": "edgar-fulltext",
    }


def _filter_sec_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return rows
    return [
        row
        for row in rows
        if needle in " ".join(str(row.get(key) or "") for key in ("title", "release", "id")).lower()
    ]


async def _fetch_sec_admin(query: str, limit: int) -> list[dict[str, Any]]:
    page = await _fetch_html(_SEC_ADMIN_URL)
    if page is None:
        return []
    rows = _filter_sec_rows(_parse_sec_admin(page), query)
    return _sort_records([_map_sec_admin(row) for row in rows], limit)


async def _fetch_sec_edgar(query: str, limit: int) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    payload = await _fetch_json(
        _SEC_FTS_URL,
        {"q": query.strip(), "page": "0", "size": str(limit)},
    )
    if payload is None:
        return []
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        return []
    items = hits.get("hits")
    if not isinstance(items, list):
        return []
    return [_map_sec_edgar(hit) for hit in items if isinstance(hit, dict)]


async def _fetch_sec(query: str, limit: int) -> list[dict[str, Any]]:
    """SEC enforcement: AAER admin listing, plus EDGAR full-text for queries."""
    admin = await _fetch_sec_admin(query, limit)
    if not query.strip():
        return admin
    edgar = await _fetch_sec_edgar(query, limit)
    return _sort_records(_dedupe_records(admin + edgar), limit)


async def _get_sec_action(value: str) -> dict[str, Any]:
    # Prefer EDGAR full-text (handles accession ids and release numbers).
    payload = await _fetch_json(_SEC_FTS_URL, {"q": value, "page": "0", "size": "1"})
    if payload is not None:
        hits = payload.get("hits")
        if isinstance(hits, dict):
            items = hits.get("hits")
            if isinstance(items, list) and items and isinstance(items[0], dict):
                hit = _map_sec_edgar(items[0])
                return {
                    "agency": "sec",
                    "id": hit["id"],
                    "title": hit["title"],
                    "summary": None,
                    "defendants": [],
                    "penalties": [],
                    "url": hit["url"],
                }
    # Fall back to the AAER admin listing (matches release numbers like
    # "34-106135" or "AAER-4595").
    page = await _fetch_html(_SEC_ADMIN_URL)
    if page is None:
        return {}
    for row in _parse_sec_admin(page):
        release = _as_text(row.get("release")) or ""
        if value in release or (row.get("id") and value == row["id"]):
            mapped = _map_sec_admin(row)
            return {
                "agency": "sec",
                "id": mapped["id"],
                "title": mapped["title"],
                "summary": None,
                "defendants": [mapped["company"]] if mapped["company"] else [],
                "penalties": [],
                "url": mapped["url"],
            }
    return {}
