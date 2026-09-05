"""Real-estate listings — Apartments.com / Zumper rental fallbacks.

Apartments.com and Zumper are rental-only sources: they are only consulted
when ``status="for_rent"``, and both sit behind aggressive anti-bot walls.

- Apartments.com — ``https://www.apartments.com/{location}/`` parses the
  embedded ``__PRELOADED_STATE__`` JSON.
- Zumper — ``https://www.zumper.com/rent-search/{location}`` parses the
  embedded ``window.__NUXT__`` JSON.

When a page looks like a CAPTCHA / challenge wall (Cloudflare, PerimeterX,
"Access denied", "Just a moment"), the source is treated as blocked and
flagged in the logs rather than parsed as an empty result — the honest
signal is "we could not read this source", never fabricated listings.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from datasets.real_estate.listings_robots import _fetch_page
from datasets.real_estate.listings_zillow import (
    _collect_dicts,
    _format_address,
    _slugify,
    _to_float,
    _to_int,
)

logger = logging.getLogger(__name__)

APARTMENTS_BASE = "https://www.apartments.com"
ZUMPER_BASE = "https://www.zumper.com"

# ── Apartments.com / Zumper embedded-state extraction ─────────────────
_PRELOADED_STATE_RE = re.compile(
    r'<script[^>]*id="__PRELOADED_STATE__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_NUXT_STATE_RE = re.compile(r"window\.__NUXT__\s*=", re.DOTALL)
# Anti-bot walls (Cloudflare / PerimeterX / CAPTCHA) must be flagged
# honestly instead of being parsed as empty results.
_BOT_MARKERS_RE = re.compile(
    r"captcha|cf-challenge|cloudflare|access denied|just a moment|"
    r"are you a human|perimeterx|puzzle|verify you are human",
    re.IGNORECASE,
)


def _extract_preloaded_state(html: str) -> dict[str, Any] | None:
    """Pull the Apartments.com ``__PRELOADED_STATE__`` JSON blob."""
    match = _PRELOADED_STATE_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_nuxt_state(html: str) -> dict[str, Any] | None:
    """Pull the Zumper ``window.__NUXT__`` JSON state (balanced-brace scan).

    The Nuxt payload is a plain JS object literal assigned to
    ``window.__NUXT__`` (not wrapped in a script tag with a JSON id), so a
    small string-aware brace scanner finds the matching close brace before
    decoding. Returns ``None`` on any failure.
    """
    match = _NUXT_STATE_RE.search(html)
    if not match:
        return None
    start = match.end()
    while start < len(html) and html[start] not in "{[":  # allow arrays too
        start += 1
    if start >= len(html) or html[start] != "{":
        return None
    opener = html[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(html):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    break
        i += 1
    if depth != 0:
        return None
    raw = html[start : i + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_bot_page(html: str) -> bool:
    """True when a page looks like a CAPTCHA / challenge wall (first 20KB)."""
    return bool(html and _BOT_MARKERS_RE.search(html[:20000]))


async def _fetch_rental_page(url: str) -> str | None:
    """Fetch a rental-source page; None on failure **or** a bot wall.

    Apartments.com and Zumper are heavily bot-protected. When the response
    looks like a CAPTCHA / challenge page we log it and return None — the
    honest signal is "blocked", not an empty result.
    """
    html = await _fetch_page(url)
    if html is None:
        return None
    if _is_bot_page(html):
        logger.warning("real_estate_rental_bot_wall", extra={"url": url[:80]})
        return None
    return html


def _apartments_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk an Apartments.com ``__PRELOADED_STATE__`` tree for listings."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    out: list[dict[str, Any]] = []
    for record in dicts:
        if not isinstance(record, dict):
            continue
        if not record.get("name"):
            continue
        if not isinstance(record.get("price"), (dict, int, float)):
            continue
        if not (record.get("address") or record.get("detailUrl")):
            continue
        out.append(record)
    return out


def _zumper_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk a Zumper ``__NUXT__`` tree for rental records."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    out: list[dict[str, Any]] = []
    for record in dicts:
        if not isinstance(record, dict):
            continue
        if not (record.get("title") or record.get("name")):
            continue
        if not isinstance(record.get("price"), (dict, int, float)):
            continue
        out.append(record)
    return out


def _normalize_apartments_listing(record: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Map an Apartments.com listing record to the canonical schema."""
    name = str(record.get("name") or "")
    address = (
        _format_address(record.get("address"))
        if isinstance(record.get("address"), dict)
        else str(record.get("address") or "")
    )
    if name and name not in address:
        address = f"{name}, {address}".strip(", ") if address else name
    url = str(record.get("detailUrl") or "")
    if url.startswith("/"):
        url = f"{APARTMENTS_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": [],
        "zestimate": None,
        "bed": _to_int(record.get("beds")),
        "bath": _to_float(record.get("baths")),
        "sqft": _to_int(record.get("sqft")),
        "days_on_market": None,
        "hoa": None,
        "url": url or base_url,
        "source": "apartments",
        "status": "For rent",
        "robots_allowed": True,
    }


def _normalize_zumper_listing(record: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Map a Zumper rental record to the canonical schema."""
    name = str(record.get("title") or record.get("name") or "")
    address = str(record.get("address") or "")
    if name and name not in address:
        address = f"{name}, {address}".strip(", ") if address else name
    url = str(record.get("url") or "")
    if url.startswith("/"):
        url = f"{ZUMPER_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": [],
        "zestimate": None,
        "bed": _to_int(record.get("bedrooms") or record.get("beds")),
        "bath": _to_float(record.get("bathrooms") or record.get("baths")),
        "sqft": _to_int(record.get("sqft")),
        "days_on_market": None,
        "hoa": None,
        "url": url or base_url,
        "source": "zumper",
        "status": "For rent",
        "robots_allowed": True,
    }


async def _search_apartments(location: str, limit: int) -> list[dict[str, Any]]:
    """Search Apartments.com for ``location`` (rentals only)."""
    slug = _slugify(location)
    if not slug:
        return []
    url = f"{APARTMENTS_BASE}/{slug}/"
    html = await _fetch_rental_page(url)
    if html is None:
        return []
    data = _extract_preloaded_state(html)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    for record in _apartments_records(data):
        out.append(_normalize_apartments_listing(record, url))
        if len(out) >= limit:
            break
    return out


async def _search_zumper(location: str, limit: int) -> list[dict[str, Any]]:
    """Search Zumper for ``location`` (rentals only)."""
    slug = _slugify(location)
    if not slug:
        return []
    url = f"{ZUMPER_BASE}/rent-search/{slug}"
    html = await _fetch_rental_page(url)
    if html is None:
        return []
    data = _extract_nuxt_state(html)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    for record in _zumper_records(data):
        out.append(_normalize_zumper_listing(record, url))
        if len(out) >= limit:
            break
    return out


async def _apartments_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Apartments.com single-listing lookup by id (often 404)."""
    url = f"{APARTMENTS_BASE}/{quote(zillow_id)}/"
    html = await _fetch_rental_page(url)
    if html is None:
        return {}
    data = _extract_preloaded_state(html)
    if data is None:
        return {}
    records = _apartments_records(data)
    if not records:
        return {}
    return _normalize_apartments_listing(records[0], url)


async def _zumper_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Zumper single-listing lookup by id (often 404)."""
    url = f"{ZUMPER_BASE}/rentals/{quote(zillow_id)}"
    html = await _fetch_rental_page(url)
    if html is None:
        return {}
    data = _extract_nuxt_state(html)
    if data is None:
        return {}
    records = _zumper_records(data)
    if not records:
        return {}
    return _normalize_zumper_listing(records[0], url)
