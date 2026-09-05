"""Blob record extraction and popular-times parsing for local_data.places.

Split from ``places.py``: shape-based normalization of decoded Google Maps
blob tuples into search-result records, the JSON-LD + blob merge for the
search page, and popular-times extraction.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re
from typing import Any

from datasets.local_data.places_config import (
    _DAY_NAMES,
    _opt_float,
    _opt_int,
    _safe_str,
)
from datasets.local_data.places_js import _extract_blobs, _iter_values
from datasets.local_data.places_jsonld import (
    _extract_cid,
    _jsonld_items,
    _record_from_jsonld,
)


def _record_name(obj: list[Any]) -> str:
    """Extract the business name from a blob result tuple."""
    cell = obj[0]
    if isinstance(cell, list) and cell and isinstance(cell[0], str):
        return cell[0].strip()
    if isinstance(cell, str):
        return cell.strip()
    return ""


def _first_external_url(obj: Any, depth: int = 0) -> str:
    """First non-Google http(s) URL found in a nested structure."""
    if depth > 3:
        return ""
    if isinstance(obj, str):
        if obj.startswith(("http://", "https://")) and not re.search(
            r"google\.|gstatic|googleusercontent|schema\.org", obj
        ):
            return obj
        return ""
    if isinstance(obj, list):
        for item in obj:
            found = _first_external_url(item, depth + 1)
            if found:
                return found
    elif isinstance(obj, dict):
        for value in obj.values():
            found = _first_external_url(value, depth + 1)
            if found:
                return found
    return ""


def _record_from_blob_tuple(obj: list[Any]) -> dict[str, Any]:
    """Normalize a Google Maps blob result tuple into a record dict.

    Layout (current Maps embed; indexes drift, all optional):
        [0]  = [name, ...]  (name cell — may also be a plain string)
        [1]  = address
        [4]  = phone
        [9]  = [rating, review_count]
        [13] = category
    Website is discovered by scanning the tuple for a non-Google URL.
    """
    rating, review_count = None, None
    if len(obj) > 9 and isinstance(obj[9], (list, tuple)) and obj[9]:
        rating = _opt_float(obj[9][0])
        review_count = _opt_int(obj[9][1] if len(obj[9]) > 1 else None)
    website = _first_external_url(obj)
    return {
        "place_id": _extract_cid(website) or "",
        "name": _record_name(obj),
        "address": _safe_str(obj[1]) if len(obj) > 1 else "",
        "phone": _safe_str(obj[4]) if len(obj) > 4 else "",
        "rating": rating,
        "review_count": review_count,
        "category": _safe_str(obj[13]) if len(obj) > 13 else "",
        "website": website,
        "hours": "",
    }


def _blob_records(blobs: list[Any]) -> list[dict[str, Any]]:
    """Extract search-result records from decoded blobs (shape-based)."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blob in blobs:
        for obj in _iter_values(blob):
            if not isinstance(obj, list) or len(obj) < 10:
                continue
            name = _record_name(obj)
            if not name or not re.search(r"[A-Za-z]", name):
                continue
            key = name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            rec = _record_from_blob_tuple(obj)
            if rec.get("name"):
                records.append(rec)
    return records


def _parse_search_results(html: str) -> list[dict[str, Any]]:
    """Parse the Maps search page into normalized records (JSON-LD + blob).

    JSON-LD records win for the fields they carry; blob records fill the
    gaps (phone, website, category, ...). Records are deduplicated by
    normalized name, preserving first-seen order.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in _jsonld_items(html):
        rec = _record_from_jsonld(item)
        key = (rec.get("name") or "").strip().lower()
        if not key:
            continue
        if key not in merged:
            merged[key] = rec
            order.append(key)
        else:
            merged[key].update({k: v for k, v in rec.items() if v not in ("", None)})
    for rec in _blob_records(_extract_blobs(html)):
        key = (rec.get("name") or "").strip().lower()
        if not key:
            continue
        if key not in merged:
            merged[key] = rec
            order.append(key)
            continue
        existing = merged[key]
        for field, value in rec.items():
            if value not in ("", None) and existing.get(field) in ("", None):
                existing[field] = value
    return [merged[key] for key in order]


# ── Popular times ────────────────────────────────────────────────────────
def _looks_like_popular_times(obj: Any) -> bool:
    """True when ``obj`` is the classic [[day, [24 hour ints]] x7] shape."""
    if not isinstance(obj, list) or len(obj) != 7:
        return False
    for entry in obj:
        if not isinstance(entry, list) or len(entry) != 2:
            return False
        day, hours = entry[0], entry[1]
        if not isinstance(day, int) or isinstance(day, bool) or not (0 <= day <= 6):
            return False
        if not isinstance(hours, list) or not (12 <= len(hours) <= 24):
            return False
        if any(not isinstance(h, int) or isinstance(h, bool) or not (0 <= h <= 100) for h in hours):
            return False
    return True


def _extract_popular_times(blobs: list[Any]) -> list[dict[str, Any]]:
    """Extract popular-times data from decoded blobs, if present."""
    for blob in blobs:
        for obj in _iter_values(blob):
            if not _looks_like_popular_times(obj):
                continue
            return [
                {
                    "day": _DAY_NAMES[entry[0] % 7],
                    "day_index": entry[0],
                    "hours": list(entry[1]),
                }
                for entry in obj
            ]
    return []
