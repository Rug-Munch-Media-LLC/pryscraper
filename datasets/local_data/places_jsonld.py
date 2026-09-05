"""JSON-LD parsing for local_data.places.

Split from ``places.py``: parsing of ``application/ld+json`` script blocks
embedded in Google Maps pages — the stable, documented data source (name,
address, rating, review count, hours) — and normalization of business-like
nodes into the canonical record dict.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from datasets.local_data.places_config import (
    _BUSINESS_TYPES,
    _LD_RE,
    _SHORT_DAY,
    _opt_float,
    _opt_int,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _iter_dicts(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield nested dict values up to ``depth``."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        yield obj
        for item in obj.values():
            yield from _iter_dicts(item, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item, depth + 1)


def _looks_like_business(obj: dict[str, Any]) -> bool:
    """True for JSON-LD nodes that look like a local-business listing."""
    types = obj.get("@type") or obj.get("type") or []
    if isinstance(types, str):
        types = [types]
    if any(isinstance(t, str) and t in _BUSINESS_TYPES for t in types):
        return True
    return bool(obj.get("name") and (obj.get("address") or obj.get("aggregateRating")))


def _jsonld_items(html: str) -> list[dict[str, Any]]:
    """Parse application/ld+json blocks, returning business-like nodes."""
    items: list[dict[str, Any]] = []
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _iter_dicts(data):
            if _looks_like_business(obj):
                items.append(obj)
    return items


def _ld_address(value: Any) -> str:
    """Render a JSON-LD address (PostalAddress dict or plain string)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [
            value.get("streetAddress"),
            value.get("addressLocality"),
            value.get("addressRegion"),
            value.get("postalCode"),
            value.get("addressCountry"),
        ]
        return ", ".join(str(p) for p in parts if p)
    return ""


def _ld_hours(value: Any) -> str:
    """Render JSON-LD opening hours to "Mon, Fri: 08:00-15:00" style."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for spec in value:
            if isinstance(spec, str):
                parts.append(spec)
                continue
            if not isinstance(spec, dict):
                continue
            days = spec.get("dayOfWeek")
            if isinstance(days, str):
                days = [days]
            opens, closes = spec.get("opens"), spec.get("closes")
            if days and opens and closes:
                day_str = ", ".join(_SHORT_DAY.get(str(d), str(d)) for d in days)
                parts.append(f"{day_str}: {opens}-{closes}")
            elif opens and closes:
                parts.append(f"{opens}-{closes}")
        return "; ".join(parts)
    return ""


def _extract_cid(value: Any) -> str | None:
    """Extract a Google Maps CID from a URL / hex ftid string."""
    if not isinstance(value, str):
        return None
    m = re.search(r"[?&]cid=(\d+)", value)
    if m:
        return m.group(1)
    m = re.search(r"0x[0-9a-f]+:0x([0-9a-f]+)", value, re.IGNORECASE)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            return None
    return None


def _record_from_jsonld(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON-LD business node into the canonical record dict."""
    rating, review_count = None, None
    agg = item.get("aggregateRating")
    if isinstance(agg, dict):
        rating = _opt_float(agg.get("ratingValue"))
        review_count = _opt_int(agg.get("reviewCount"))
    types = item.get("@type") or item.get("type") or []
    if isinstance(types, str):
        types = [types]
    category = ", ".join(
        str(t) for t in types if isinstance(t, str) and t not in ("LocalBusiness", "Place")
    )
    url = item.get("url") or item.get("sameAs") or ""
    same_as = item.get("sameAs")
    website = ""
    if isinstance(same_as, str) and same_as.startswith("http") and "google" not in same_as.lower():
        website = same_as
    if (
        not website
        and isinstance(url, str)
        and url.startswith("http")
        and "google" not in url.lower()
    ):
        website = url
    return {
        "place_id": _extract_cid(url) or "",
        "name": str(item.get("name") or ""),
        "address": _ld_address(item.get("address")),
        "phone": str(item.get("telephone") or item.get("phone") or ""),
        "rating": rating,
        "review_count": review_count,
        "category": category,
        "website": website,
        "hours": _ld_hours(item.get("openingHoursSpecification") or item.get("openingHours")),
    }
