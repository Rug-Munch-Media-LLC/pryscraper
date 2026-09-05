"""Generic record helpers for the enforcement sources (``compliance_data``).

Value coercion, date normalization, HTML stripping, record sorting and
deduplication shared by the per-agency parser/mapper modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import re
from typing import Any

from datasets.compliance_data._enforcement_data import _AGENCIES


def _as_text(value: Any) -> str | None:
    """Coerce a JSON/HTML value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(value: str | None) -> str | None:
    """Normalize API dates to ``YYYY-MM-DD`` (or passthrough)."""
    if not value:
        return None
    text = value.strip()
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text or None


def _mmddyyyy_date(value: str | None) -> str | None:
    """Normalize a ``MM/DD/YYYY`` date (EPA ECHO / OSHA IMIS) to ``YYYY-MM-DD``."""
    if not value:
        return None
    text = value.strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text or None


def _strip_tags(raw: str | None) -> str | None:
    """Strip HTML tags/entities from a scraped title fragment."""
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(text).strip()
    return text or None


def _sort_records(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sort newest-first (missing dates last) and cap at ``limit``."""
    records.sort(key=lambda record: str(record.get("date") or ""), reverse=True)
    return records[:limit]


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop records whose ``id`` was already seen (first occurrence wins)."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        rid = str(record.get("id") or "")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        result.append(record)
    return result


def _parse_agencies(agencies: str) -> list[str]:
    """Resolve an agencies spec ('all' or comma-separated) to a list."""
    value = str(agencies or "all").strip().lower()
    if not value or value == "all":
        return list(_AGENCIES)
    result: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if part in _AGENCIES and part not in result:
            result.append(part)
    return result
