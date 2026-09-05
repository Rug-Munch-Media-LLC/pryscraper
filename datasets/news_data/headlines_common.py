"""Shared helpers for news headline collection (GDELT + RSS).

Low-level utilities used by the fetchers and parsers: limit/timeframe
sanitization, URL hostname extraction, GDELT date parsing and the shared
HTTP client configuration.

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
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

_MAX_LIMIT = 250  # GDELT MAXRECORDS cap (artlist mode)
_DEFAULT_LIMIT = 20
_DEFAULT_TIMEFRAME = "24h"

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,application/rss+xml,text/xml,text/html;q=0.9,*/*;q=0.8",
}

_TIMEFRAME_RE = re.compile(r"^\d+(min|h|hours|d|days|w|weeks|m|months)$")
_SEENDATE_RE = re.compile(r"^(\d{8})T(\d{6})Z$")


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _sanitize_timeframe(timeframe: Any) -> str:
    """Return a GDELT ``timespan`` value, or the default when malformed."""
    if isinstance(timeframe, str) and _TIMEFRAME_RE.match(timeframe.strip()):
        return timeframe.strip()
    return _DEFAULT_TIMEFRAME


def _hostname(url: str) -> str:
    """Return the bare hostname of a URL ('' when unparseable)."""
    try:
        return urlparse(url).netloc.lower() or ""
    except ValueError:
        return ""


def _parse_seendate(value: str) -> str:
    """Convert GDELT ``YYYYMMDDTHHMMSSZ`` to ``YYYY-MM-DDTHH:MM:SSZ``.

    Returns ``""`` when the value is not in GDELT's format (e.g. RSS
    ``pubDate`` is handled separately).
    """
    match = _SEENDATE_RE.match(value.strip() if isinstance(value, str) else "")
    if not match:
        return ""
    date_part, time_part = match.groups()
    try:
        dt = datetime.strptime(f"{date_part}T{time_part}Z", "%Y%m%dT%H%M%SZ")
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
