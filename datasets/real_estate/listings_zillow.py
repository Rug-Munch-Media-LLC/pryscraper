"""Real-estate listings — Zillow ``__NEXT_DATA__`` parsing + shared helpers.

Zillow has no public listing API since 2021, so listings are extracted from
the public ``www.zillow.com`` pages themselves: the Next.js pages embed a
``__NEXT_DATA__`` script tag (plus an Apollo/REDUX-style state cache) that
contains the listing/search payload as JSON. This module parses that embedded
JSON directly — no paid API, no credentials.

This module also hosts the shared record-normalization helpers used by the
Redfin and rental-source modules (address formatting, scalar coercion,
recursive dict collection).

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
from pathlib import Path
from typing import Any
from urllib.parse import quote

from datasets.real_estate.listings_robots import _fetch_page

logger = logging.getLogger(__name__)

ZILLOW_BASE = "https://www.zillow.com"

# ── Static config tables (loaded from listings.json) ──────────────────
# Zillow robots.txt allows /homes/for_sale/, /homes/for_rent/ and
# /homes/recently_sold/ browse paths for the generic agent; the modern
# ``/homes/{location}_rb/`` and ``/homedetails/`` paths are not on the
# allow-list, so the compliant URL forms are used here.
_DATA_PATH = Path(__file__).with_name("listings.json")


def _load_data() -> dict[str, Any]:
    """Load the static config tables from the sibling ``listings.json``."""
    try:
        with open(_DATA_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        logger.warning("real_estate_listings_data_unreadable", extra={"path": str(_DATA_PATH)})
        return {}
    return data if isinstance(data, dict) else {}


_DATA = _load_data()
_ZILLOW_STATUS_PATHS: dict[str, str] = _DATA.get("zillow_status_paths", {})
_ZILLOW_STATUS_FILTERS: dict[str, dict[str, Any]] = _DATA.get("zillow_status_filters", {})


# ── URL builders ───────────────────────────────────────────────────────
def _slugify(location: str) -> str:
    """``Austin, TX`` -> ``austin-tx`` (Zillow search-path style)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip().lower()).strip("-")
    return quote(slug) if slug else ""


# ── __NEXT_DATA__ extraction ───────────────────────────────────────────
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_next_data(html: str) -> dict[str, Any] | None:
    """Pull the Next.js ``__NEXT_DATA__`` JSON blob out of a Zillow page."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ── Shared JSON-tree / scalar helpers (used by all source modules) ─────
def _collect_dicts(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    """Recursively collect every dict in a JSON tree (max depth 16 / 8000 nodes).

    JSON-string values (Zillow's ``gdpClientCache`` / Apollo cache stores
    payloads as escaped strings) are decoded and walked too, so the parser is
    resilient to Zillow's cache schema drifting.
    """
    if depth > 16 or len(out) >= 8000:
        return
    if isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            _collect_dicts(value, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_dicts(item, out, depth + 1)
    elif isinstance(obj, str) and len(obj) > 2 and obj.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(obj)
        except json.JSONDecodeError:
            return
        _collect_dicts(decoded, out, depth + 1)


def _first_value(
    dicts: list[dict[str, Any]], key: str, types: tuple[type, ...] | None = None
) -> Any:
    """First non-empty match for ``key`` across collected dicts."""
    for item in dicts:
        if key not in item:
            continue
        value = item[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        if types is None or isinstance(value, types):
            return value
    return None


def _unwrap_value(value: Any) -> Any:
    """Zillow/Redfin wrap scalars in dicts like ``{value: ...}`` — unwrap."""
    if isinstance(value, dict):
        for candidate in ("value", "amount", "fee", "min", "max"):
            if candidate in value and value[candidate] is not None:
                return value[candidate]
        return None
    return value


def _to_int(value: Any) -> int | None:
    value = _unwrap_value(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    value = _unwrap_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_address(raw: Any) -> str:
    """Build ``Street, City, ST zip`` from Zillow's address dict shapes."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    street = raw.get("streetAddress") or raw.get("streetAddressLine") or ""
    city = raw.get("city") or ""
    state = raw.get("state") or ""
    zipcode = raw.get("zipcode") or raw.get("zip") or raw.get("postalCode") or ""
    parts = [str(street).strip(), str(city).strip()]
    state_zip = " ".join(p for p in (str(state).strip(), str(zipcode).strip()) if p)
    if state_zip:
        parts.append(state_zip)
    return ", ".join(p for p in parts if p)


def _normalize_price_history(raw: Any) -> list[dict[str, Any]]:
    """Normalize Zillow ``priceHistory`` entries to ``{date, price, event}``."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "date": entry.get("date") or entry.get("displayDate") or "",
                "price": _to_int(entry.get("price")),
                "event": entry.get("event") or entry.get("eventName") or "",
            }
        )
    return out


def _normalize_listing(
    record: dict[str, Any],
    *,
    source: str,
    fallback_url: str,
    status: str = "",
) -> dict[str, Any]:
    """Map a parsed Zillow/Redfin record to the canonical listing schema."""
    address = _format_address(record.get("address")) or _format_address(
        record.get("addressComponents")
    )
    if not address:
        street = record.get("streetAddress")
        if isinstance(street, str):
            address = street
    hoa_raw = record.get("hoa") or record.get("hoaFee")
    hoa = _to_float(hoa_raw) if hoa_raw is not None else None
    url = record.get("url") or record.get("detailUrl") or record.get("hdpUrl") or fallback_url
    if url.startswith("/"):
        url = f"{ZILLOW_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": _normalize_price_history(record.get("priceHistory")),
        "zestimate": _to_int(record.get("zestimate")),
        "bed": _to_int(record.get("bedrooms") or record.get("beds")),
        "bath": _to_float(record.get("bathrooms") or record.get("baths")),
        "sqft": _to_int(record.get("livingArea") or record.get("sqFt")),
        "days_on_market": _to_int(record.get("daysOnZillow") or record.get("daysOnMarket")),
        "hoa": hoa,
        "url": url,
        "source": source,
        "status": status,
        "robots_allowed": True,
    }


# ── Zillow parsers ────────────────────────────────────────────────────
def _parse_zillow_listing(data: dict[str, Any], url: str) -> dict[str, Any]:
    """Extract a listing from a Zillow homedetails ``__NEXT_DATA__`` tree."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    if not dicts:
        return {}

    record = _normalize_listing(dicts[0], source="zillow", fallback_url=url)
    record["address"] = (
        _format_address(_first_value(dicts, "address"))
        or _format_address(_first_value(dicts, "addressComponents"))
        or record["address"]
    )
    record["price"] = _to_int(_first_value(dicts, "price")) or record["price"]
    record["zestimate"] = _to_int(_first_value(dicts, "zestimate")) or record["zestimate"]
    record["bed"] = (
        _to_int(_first_value(dicts, "bedrooms"))
        or _to_int(_first_value(dicts, "beds"))
        or record["bed"]
    )
    record["bath"] = (
        _to_float(_first_value(dicts, "bathrooms"))
        or _to_float(_first_value(dicts, "baths"))
        or record["bath"]
    )
    record["sqft"] = (
        _to_int(_first_value(dicts, "livingArea"))
        or _to_int(_first_value(dicts, "sqFt"))
        or record["sqft"]
    )
    record["days_on_market"] = (
        _to_int(_first_value(dicts, "daysOnZillow"))
        or _to_int(_first_value(dicts, "daysOnMarket"))
        or record["days_on_market"]
    )
    hoa = _first_value(dicts, "hoa")
    if hoa is not None:
        record["hoa"] = _to_float(hoa)
    history = _first_value(dicts, "priceHistory")
    if history is not None:
        record["price_history"] = _normalize_price_history(history)
    status = _first_value(dicts, "homeStatus")
    if isinstance(status, str):
        record["status"] = status
    record["robots_allowed"] = True
    return record


def _parse_zillow_search(data: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    """Extract ``listResults`` from a Zillow SRP ``__NEXT_DATA__`` tree."""
    try:
        state = data["props"]["pageProps"]["searchPageState"]
    except (KeyError, TypeError):
        return []
    results = state.get("cat1", {}).get("searchResults", {}).get("listResults", [])
    if not isinstance(results, list):
        return []
    out: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        merged = dict(item)
        home_info = item.get("hdpData", {}).get("homeInfo")
        if isinstance(home_info, dict):
            merged.update(home_info)
        record = _normalize_listing(merged, source="zillow", fallback_url=base_url)
        record["status"] = item.get("statusText") or item.get("statusType") or ""
        out.append(record)
    return out


async def _search_zillow(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    """Search the Zillow SRP for ``location`` (embedded ``__NEXT_DATA__``)."""
    slug = _slugify(location)
    if not slug:
        return []
    search_path = _ZILLOW_STATUS_PATHS.get(status, "for_sale")
    base_url = f"{ZILLOW_BASE}/homes/{search_path}/{slug}/"
    filter_state = {
        key: {"value": value}
        for key, value in _ZILLOW_STATUS_FILTERS.get(
            status, _ZILLOW_STATUS_FILTERS["for_sale"]
        ).items()
    }
    query_state = {
        "pagination": {},
        "isMapVisible": False,
        "filterState": filter_state,
        "isListVisible": True,
        "mapZoom": 5,
    }
    url = (
        f"{base_url}?searchQueryState={quote(json.dumps(query_state))}&searchQueryStateVersion=0.1"
    )
    html = await _fetch_page(url)
    if html is None:
        return []
    data = _extract_next_data(html)
    if data is None:
        return []
    results = _parse_zillow_search(data, base_url)
    return results[:limit]
