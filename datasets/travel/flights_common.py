"""Shared constants and validation helpers for the Google Flights scraper.

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
from datetime import datetime, timedelta

# Grid bounds: never fetch more than this many days in one call, and cap
# per-day option scans so a single grid run stays within sane HTTP volume.
_MAX_GRID_DAYS = 30
_MAX_RESULTS = 200

_AIRLINE_RE = re.compile(r"^[A-Za-z][A-Za-z .&'\-]{1,39}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE_RE = re.compile(r"^[A-Z]{3}$")
_DURATION_STR_RE = re.compile(
    r"(?:(\d+)\s*(?:hr|h|hour)s?)?\s*(?:(\d+)\s*(?:min|m))?", re.IGNORECASE
)


# ── date / airport-code validation ─────────────────────────────────────
def _valid_date(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not _DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_code(value: str) -> str:
    if not isinstance(value, str):
        return ""
    code = value.strip().upper()
    return code if _CODE_RE.fullmatch(code) else ""


def _date_range(start_date: str, end_date: str) -> list[str]:
    """List ``YYYY-MM-DD`` strings in ``[start_date, end_date]`` (bounded)."""
    if not _valid_date(start_date) or not _valid_date(end_date):
        return []
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return []
    if end < start:
        return []
    end = min(end, start + timedelta(days=_MAX_GRID_DAYS - 1))
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days
