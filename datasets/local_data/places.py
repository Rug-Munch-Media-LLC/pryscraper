"""Google Maps local-business data extraction for Pry.

Scrapes the public Google Maps search page (``google.com/maps/search/...``)
for local-business listings and the place page (``?cid=`` / ``/place/``)
for detail + popular times. This is lead-gen data: name, address, phone,
rating, review count, category, website and opening hours.

Data sources, in priority order:

1. ``application/ld+json`` script blocks embedded in the page — stable,
   documented fields (name, address, rating, review count, hours).
2. The ``window._p`` / ``window.APP_INITIALIZATION_STATE`` JS blobs — the
   full listing payload (phone, category, website, popular times). These
   blobs are undocumented; Google moves the indexes without notice, so the
   blob parser is deliberately shape-based and defensive — every field
   defaults to ``""`` / ``None`` rather than raising.

Anti-bot note:
    Google Maps is a JavaScript-heavy page. A plain HTTP GET returns the
    HTML shell with the embedded JSON, but Google frequently gates it
    behind consent walls / "unusual traffic" / captcha challenges. When
    that happens the module logs ``google_maps_anti_bot`` and returns
    empty results — the escalation path is the repo's browser/stealth
    tier (``camoufox_integration``, ``stealth_engine``), not this module.

Contract:
    * ``search_places(query, location, limit)`` → list of normalized records
    * ``get_place(place_id)`` → single record + ``popular_times``

Both are async and never raise; on any failure they return ``[]`` / ``{}``.
robots.txt is respected (best-effort, fail-open — see ``_robots_allowed``).

Implementation is split across cohesive sibling modules; this file is the
facade and re-exports the internals so existing imports
(``datasets.local_data.places._extract_blobs`` etc.) keep working:

* ``places_config``  — constants, caches, coercion helpers
* ``places_http``    — retrying HTTP GET + robots.txt compliance
* ``places_js``      — embedded JS blob decoding
* ``places_jsonld``  — JSON-LD parsing / normalization
* ``places_blob``    — blob record extraction + popular times
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from datasets.local_data.places_blob import (
    _blob_records,
    _extract_popular_times,
    _parse_search_results,
)
from datasets.local_data.places_config import (
    GOOGLE_MAPS_CID,
    GOOGLE_MAPS_PLACE,
    GOOGLE_MAPS_SEARCH,
    _cache_get,
    _cache_set,
    _clear_cache,  # noqa: F401 — re-exported for backward compatibility
)
from datasets.local_data.places_http import _http_get, _robots_allowed
from datasets.local_data.places_js import (
    _extract_blobs,
    _is_anti_bot,
    _iter_values,  # noqa: F401 — re-exported (reviews.py imports it from here)
)
from datasets.local_data.places_jsonld import (
    _extract_cid,  # noqa: F401 — re-exported for backward compatibility
    _jsonld_items,
    _record_from_jsonld,
)

logger = logging.getLogger(__name__)

__all__ = ["get_place", "search_places"]


# ── Public API (never raises) ────────────────────────────────────────────
def _place_url(place_id: str) -> str:
    """Build a Google Maps place page URL from a CID / hex / slug place_id."""
    pid = place_id.strip()
    m = re.fullmatch(r"0x[0-9a-f]+:0x([0-9a-f]+)", pid, re.IGNORECASE)
    if m:
        try:
            return GOOGLE_MAPS_CID.format(cid=str(int(m.group(1), 16)))
        except ValueError:
            pass  # not a hex CID after all — fall through to digit/verbatim handling
    if pid.isdigit():
        return GOOGLE_MAPS_CID.format(cid=pid)
    return GOOGLE_MAPS_PLACE.format(slug=quote(pid))


def _extract_place_detail(html: str, blobs: list[Any]) -> dict[str, Any]:
    """Best-effort place-detail record from a place page."""
    for item in _jsonld_items(html):
        rec = _record_from_jsonld(item)
        if rec.get("name"):
            return rec
    records = _blob_records(blobs)
    if records:
        return records[0]
    return {}


async def search_places(query: str, location: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Google Maps business search. Never raises; [] on any failure."""
    try:
        q = f"{query} {location}".strip()
        if not q:
            return []
        cache_key = f"search:{q.lower()}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return list(cached)[:limit]
        url = GOOGLE_MAPS_SEARCH.format(query=quote(q))
        if not await _robots_allowed(url):
            return []
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            return []
        records = _parse_search_results(resp.text)
        if not records and _is_anti_bot(resp.text):
            logger.warning(
                "google_maps_anti_bot",
                extra={
                    "query": q,
                    "hint": "requires repo browser/stealth tier (camoufox/stealth_engine)",
                },
            )
        _cache_set(cache_key, records)
        return list(records)[:limit]
    except Exception:  # public API boundary: never-raise contract
        logger.exception("search_places_failed")
        return []


async def get_place(place_id: str) -> dict[str, Any]:
    """Google Maps place detail (+ popular_times). Never raises; {} on failure."""
    try:
        pid = str(place_id or "").strip()
        if not pid:
            return {}
        url = _place_url(pid)
        if not await _robots_allowed(url):
            return {}
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            return {}
        html = resp.text
        blobs = _extract_blobs(html)
        record = _extract_place_detail(html, blobs)
        if not record:
            if _is_anti_bot(html):
                logger.warning(
                    "google_maps_anti_bot",
                    extra={"place_id": pid, "hint": "requires repo browser/stealth tier"},
                )
            return {}
        popular = _extract_popular_times(blobs)
        if popular:
            record["popular_times"] = popular
        record["source"] = "google"
        return record
    except Exception:  # public API boundary: never-raise contract
        logger.exception("get_place_failed")
        return {}
