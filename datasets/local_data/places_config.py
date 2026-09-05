"""Configuration, constants, and small coercion helpers for local_data.places.

Split from ``places.py``: URLs, headers, timeouts, retry policy, in-memory
caches, and the defensive ``_opt_*`` coercion helpers shared by the JSON-LD
and blob parsers. Static lookup tables (business types, day names, anti-bot
signals) live in ``places_data.json`` next to this module.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

# ── Configuration ────────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_RETRIES = 3
RETRY_BASE = 0.8
MAX_BACKOFF = 6.0
RESULT_CACHE_TTL = 30.0  # in-memory result cache TTL (seconds)
ROBOTS_CACHE_TTL = 300.0  # robots.txt per-host cache TTL (seconds)

GOOGLE_MAPS_SEARCH = "https://www.google.com/maps/search/{query}"
GOOGLE_MAPS_CID = "https://www.google.com/maps?cid={cid}"
GOOGLE_MAPS_PLACE = "https://www.google.com/maps/place/{slug}"

# Browser-ish headers: Google serves the JS page (with the embedded JSON
# blobs) to normal user agents; a bare "pry/3.0" UA gets the no-JS shell.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Static lookup tables (loaded from places_data.json) ──────────────────
_DATA_PATH = Path(__file__).with_name("places_data.json")
with _DATA_PATH.open(encoding="utf-8") as _fh:
    _DATA = json.load(_fh)

_BUSINESS_TYPES = frozenset(_DATA["business_types"])
_DAY_NAMES: list[str] = _DATA["day_names"]
_SHORT_DAY: dict[str, str] = _DATA["short_day"]
_ANTI_BOT_SIGNALS: tuple[str, ...] = tuple(_DATA["anti_bot_signals"])

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_BLOB_ASSIGN_RE = re.compile(r"window\.(_p|APP_INITIALIZATION_STATE)\s*=")

_cache: dict[str, tuple[float, Any]] = {}
_robots_cache: dict[str, tuple[float, bool]] = {}


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    _cache.clear()
    _robots_cache.clear()


# ── Small coercion helpers ───────────────────────────────────────────────
def _opt_float(value: Any) -> float | None:
    """Coerce a value to float; None on any failure."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[no-any-return]
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    """Coerce a value to int, tolerating "2,341 reviews" style strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _safe_str(value: Any) -> str:
    """Return value when it is a str, else ""."""
    return value if isinstance(value, str) else ""


def _cache_get(key: str) -> Any | None:
    """Return a cached value, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > RESULT_CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    """Store a value under ``key``."""
    _cache[key] = (time.monotonic(), value)


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    """Exponential backoff, honoring Retry-After when present."""
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF)
            except ValueError:
                pass  # malformed Retry-After header — fall back to default backoff
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)
