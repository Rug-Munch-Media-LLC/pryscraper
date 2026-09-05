"""Shared constants, coercers, and normalization for the energy LMP dataset.

Split out of ``datasets/energy_data/lmp.py`` so each ISO fetcher module can
stay focused; this module holds only cross-ISO plumbing (HTTP defaults,
value coercion, timezone conversion, region/date normalization).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

_TIMEOUT = httpx.Timeout(20.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-energy/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "text/csv, application/json, */*",
}

# NYISO timestamps are ET wall-clock; convert via America/New_York when the
# host has tzdata, else degrade to naive ISO (never crash at import time).
_ET: ZoneInfo | None
try:
    _ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # pragma: no cover - tzdata-less hosts
    _ET = None

# ERCOT dashboard timestamps are CT wall-clock; convert via America/Chicago.
_CT: ZoneInfo | None
try:
    _CT = ZoneInfo("America/Chicago")
except ZoneInfoNotFoundError:  # pragma: no cover - tzdata-less hosts
    _CT = None

_ALL_REGIONS = ("nyiso", "pjm", "ercot", "caiso")
_REGION_ALIASES = {
    "nyiso": "nyiso",
    "new york": "nyiso",
    "pjm": "pjm",
    "ercot": "ercot",
    "texas": "ercot",
    "caiso": "caiso",
    "california": "caiso",
}


# ── value coercers ────────────────────────────────────────────────────


def _as_text(value: Any) -> str | None:
    """Coerce a JSON/CSV value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    """Coerce a JSON/CSV value to float/None ('' -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── timestamp converters ──────────────────────────────────────────────


def _nyiso_ts_to_utc(value: str) -> str:
    """Convert NYISO's ET wall-clock timestamp to ISO-8601 UTC.

    NYISO files carry naive Eastern Time (no DST marker); the zoneinfo
    conversion is DST-aware. Falls back to the raw value when the host has
    no tzdata (``_ET is None``).
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        local = datetime.strptime(text, "%m/%d/%Y %H:%M")
    except ValueError:
        return text
    if _ET is None:
        return local.isoformat()
    try:
        return local.replace(tzinfo=_ET).astimezone(UTC).isoformat()
    except (ValueError, OverflowError):  # pragma: no cover - defensive, never raise
        return local.isoformat()


def _ct_ts_to_utc(value: str) -> str:
    """Convert a Central Time wall-clock timestamp to ISO-8601 UTC.

    Used by the ERCOT dashboard feed (naive CT, no DST marker). Falls back
    to the raw value when tzdata is missing (``_CT is None``).
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        local = datetime.strptime(text, "%m/%d/%Y %H:%M")
    except ValueError:
        return text
    if _CT is None:
        return local.isoformat()
    try:
        return local.replace(tzinfo=_CT).astimezone(UTC).isoformat()
    except (ValueError, OverflowError):  # pragma: no cover - defensive, never raise
        return local.isoformat()


def _iso_utc(value: str) -> str:
    """Normalize a (possibly naive) ISO-8601 string to ISO-8601 UTC."""
    text = (value or "").strip().replace("Z", "+00:00")
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


# ── region / date normalization ───────────────────────────────────────


def _normalize_region(region: str) -> list[str]:
    """Resolve a region name to the ISO list to fetch ([] = unknown)."""
    text = (region or "").strip().lower()
    if not text:
        return []
    if text == "all":
        return list(_ALL_REGIONS)
    if text in _REGION_ALIASES:
        return [_REGION_ALIASES[text]]
    return []


def _normalize_date(date: str) -> str | None:
    """Return 'YYYYMMDD' for 'today' / 'YYYY-MM-DD' / 'YYYYMMDD', else None."""
    text = (date or "").strip().lower()
    if not text:
        return None
    if text == "today":
        return datetime.now(UTC).date().strftime("%Y%m%d")
    compact = text.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return compact
    return None
