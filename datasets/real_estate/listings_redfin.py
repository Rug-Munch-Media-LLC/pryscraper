"""Real-estate listings — Redfin GIS API fallback.

Redfin's public ``/stingray/api/gis`` endpoint is the JSONP endpoint
Redfin's own website uses; it returns ``{}&&{...}`` wrapped JSON. The
per-home detail endpoint (``/stingray/api/home/details/initialInfo``)
is attempted for single-listing lookups but is bot-protected from many
networks — it degrades to ``{}`` when blocked.

Redfin GIS ``status`` codes: 9 = active, 1 = rental, 11 = sold. Verified
Redfin region ids (``region_type=6``) live in the sibling
``listings.json``; extend via ``PRY_REAL_ESTATE_REDFIN_REGION_IDS``
(JSON ``{"location": id}``).

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
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from datasets.real_estate import listings_robots as _http
from datasets.real_estate.listings_robots import (
    _robots_allowed,
    _sleep_for_robots,
)
from datasets.real_estate.listings_zillow import (
    _fetch_page,
    _format_address,
    _normalize_price_history,
    _to_float,
    _to_int,
    _unwrap_value,
)

logger = logging.getLogger(__name__)

REDFIN_BASE = "https://www.redfin.com"

_REDFIN_STATUS_CODES: dict[str, str] = {}
_REDFIN_REGION_IDS: dict[str, int] = {}
try:  # static tables come from the sibling listings.json (loaded by zillow mod)
    from datasets.real_estate.listings_zillow import _DATA

    _REDFIN_STATUS_CODES = _DATA.get("redfin_status_codes", {})
    _REDFIN_REGION_IDS = _DATA.get("redfin_region_ids", {})
except Exception:  # pragma: no cover  # noqa: BLE001, S110  - defensive; _DATA load never raises
    pass
_REDFIN_REGION_ENV = "PRY_REAL_ESTATE_REDFIN_REGION_IDS"


def _redfin_region_id(location: str) -> int | None:
    """Resolve a location to a Redfin region id (numeric passthrough / map)."""
    stripped = location.strip()
    if stripped.isdigit():
        return int(stripped)
    key = re.sub(r"[^a-zA-Z0-9]+", "-", stripped.lower()).strip("-")
    if key in _REDFIN_REGION_IDS:
        return _REDFIN_REGION_IDS[key]
    raw = os.environ.get(_REDFIN_REGION_ENV)
    if raw:
        try:
            extra = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("real_estate_region_env_invalid", extra={"value": raw[:80]})
            extra = {}
        if isinstance(extra, dict) and key in extra:
            try:
                return int(extra[key])
            except (TypeError, ValueError):
                return None
    return None


async def _fetch_redfin_json(params: dict[str, str]) -> dict[str, Any] | None:
    """GET the Redfin GIS JSONP endpoint and decode the ``{}&&{...}`` wrapper."""
    url = f"{REDFIN_BASE}/stingray/api/gis"
    if not await _robots_allowed(url):
        if _http._robots_enforced():
            logger.warning("real_estate_robots_blocked", extra={"url": url})
            return None
        logger.warning("real_estate_robots_disallowed_fetching", extra={"url": url})
    await _sleep_for_robots(url)

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_http._TIMEOUT, headers=_http._HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            raw = response.text
        return _http._redfin_jsonp_payload(raw)

    try:
        return await _http.async_retry(_one, config=_http._RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
        return None


# ── Redfin mapping ─────────────────────────────────────────────────────
def _redfin_address(home: dict[str, Any], url: str) -> str:
    """Best-effort address from a Redfin GIS home (list payload lacks street)."""
    city = str(home.get("city") or "")
    state = str(home.get("state") or "")
    zipcode = str(home.get("zip") or "")
    parts = [p for p in (city, f"{state} {zipcode}".strip()) if p]
    base = ", ".join(parts)
    # The URL slug carries the street: /WA/Seattle/732-11th-Ave-E-98102/home/52821
    if "/home/" in url:
        street = url.split("/home/")[0].rsplit("/", 1)[-1]
        street = street.replace("-", " ")
        if street and not street[0].isdigit():
            street = ""
        if street:
            return f"{street}, {base}" if base else street
    return base


def _normalize_redfin_home(home: dict[str, Any], status: str) -> dict[str, Any]:
    """Map a Redfin GIS home entry to the canonical listing schema."""
    url = home.get("url") or ""
    if url.startswith("/"):
        url = f"{REDFIN_BASE}{url}"
    hoa_raw = _unwrap_value(home.get("hoa"))
    return {
        "address": _redfin_address(home, url),
        "price": _to_int(home.get("price")),
        "price_history": [],
        "zestimate": _to_int(home.get("zestimate")),
        "bed": _to_int(home.get("beds")),
        "bath": _to_float(home.get("baths") or home.get("fullBaths")),
        "sqft": _to_int(home.get("sqFt")),
        "days_on_market": _to_int(home.get("dom")),
        "hoa": _to_float(hoa_raw) if hoa_raw is not None else None,
        "url": url,
        "source": "redfin",
        "status": str(home.get("mlsStatus") or status),
        "robots_allowed": True,
    }


def _normalize_redfin_detail(home: dict[str, Any], zillow_id: str) -> dict[str, Any]:
    """Map a Redfin ``initialInfo`` homeInfo payload to the listing schema."""
    url = home.get("url") or f"{REDFIN_BASE}/homes/{zillow_id}"
    hoa_raw = home.get("hoa")
    address = _format_address(home.get("address")) or _format_address(
        {
            "streetAddress": home.get("streetAddress"),
            "city": home.get("city"),
            "state": home.get("state"),
            "zipcode": home.get("zip") or home.get("zipcode"),
        }
    )
    return {
        "address": address,
        "price": _to_int(home.get("price")),
        "price_history": _normalize_price_history(home.get("priceHistory")),
        "zestimate": _to_int(home.get("zestimate")),
        "bed": _to_int(home.get("beds")),
        "bath": _to_float(home.get("baths")),
        "sqft": _to_int(home.get("sqFt")),
        "days_on_market": _to_int(home.get("daysOnMarket")),
        "hoa": _to_float(hoa_raw) if hoa_raw is not None else None,
        "url": url if url.startswith("http") else f"{REDFIN_BASE}{url}",
        "source": "redfin",
        "status": str(home.get("status") or ""),
        "robots_allowed": True,
    }


async def _redfin_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Redfin single-listing lookup (often CDN-blocked -> {})."""
    url = f"{REDFIN_BASE}/stingray/api/home/details/initialInfo?path={quote(f'/homes/{zillow_id}')}"
    html = await _fetch_page(url)
    if html is None:
        return {}
    try:
        payload = json.loads(html)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    info = (payload.get("payload") or {}).get("homeInfo") or {}
    if not isinstance(info, dict) or not info:
        return {}
    return _normalize_redfin_detail(info, zillow_id)


async def _search_redfin(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    """Search Redfin's GIS endpoint for ``location`` (region-id resolved)."""
    region_id = _redfin_region_id(location)
    if region_id is None:
        logger.warning("real_estate_redfin_region_unresolved", extra={"location": location})
        return []
    params = {
        "al": "1",
        "region_id": str(region_id),
        "region_type": "6",
        "status": _REDFIN_STATUS_CODES[status],
        "uipt": "1",
        "v": "8",
        "num_homes": str(limit),
    }
    payload = await _fetch_redfin_json(params)
    if payload is None:
        return []
    homes = (payload.get("payload") or {}).get("homes") or []
    return [_normalize_redfin_home(home, status) for home in homes if isinstance(home, dict)][
        :limit
    ]
