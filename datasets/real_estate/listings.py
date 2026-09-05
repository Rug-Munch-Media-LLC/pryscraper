"""Real-estate listings — public facade over per-source modules.

Zillow has no public listing API since 2021, so listings are extracted from
the public ``www.zillow.com`` pages themselves: the Next.js pages embed a
``__NEXT_DATA__`` script tag (plus an Apollo/REDUX-style state cache) that
contains the listing/search payload as JSON. Parsing lives in
:mod:`listings_zillow`; the robots.txt/HTTP layer in :mod:`listings_robots`;
the Redfin GIS fallback in :mod:`listings_redfin`; and the rental-only
Apartments.com / Zumper fallbacks in :mod:`listings_rentals`.

When Zillow is unreachable or returns a non-200/parseable page, ``search``
falls back through a guarded chain:

1. Redfin's public ``/stingray/api/gis`` endpoint. Redfin's per-home
   detail endpoint is attempted for single-listing lookups but is
   bot-protected from many networks — it degrades to ``{}`` when blocked.
2. Apartments.com (rentals only) — embedded ``__PRELOADED_STATE__`` JSON.
3. Zumper (rentals only) — embedded ``window.__NUXT__`` JSON.

Apartments.com and Zumper are rental-only sources: they are only consulted
when ``status="for_rent"``. When a page looks like a CAPTCHA / challenge
wall, the source is treated as blocked and flagged in the logs rather than
parsed as an empty result — the honest signal is "we could not read this
source", never fabricated listings.

Contract (both functions)
-------------------------
* async, never raise
* ``get_listing`` -> dict (``{}`` on failure)
* ``search_listings`` -> list[dict] (``[]`` on failure)

robots.txt + backoff policy: see :mod:`listings_robots`.

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
from typing import Any

from datasets.real_estate.listings_redfin import (
    _REDFIN_STATUS_CODES,
    _redfin_listing_fallback,
    _search_redfin,
)
from datasets.real_estate.listings_rentals import (
    _apartments_listing_fallback,
    _extract_nuxt_state,  # noqa: F401 (re-exported for tests)
    _extract_preloaded_state,  # noqa: F401 (re-exported for tests)
    _is_bot_page,  # noqa: F401 (re-exported for tests)
    _search_apartments,
    _search_zumper,
    _zumper_listing_fallback,
)
from datasets.real_estate.listings_robots import (  # noqa: F401 (re-exported)
    _RETRY_CONFIG,
    _fetch_page,
    _robots_allowed,
    _sleep_for_robots,
    reset_robots_cache,
)
from datasets.real_estate.listings_zillow import (
    ZILLOW_BASE,
    _extract_next_data,
    _format_address,  # noqa: F401 (re-exported for tests)
    _normalize_price_history,  # noqa: F401 (re-exported for tests)
    _parse_zillow_listing,
    _search_zillow,
    _slugify,  # noqa: F401 (re-exported for tests)
    _to_int,  # noqa: F401 (re-exported for tests)
)

logger = logging.getLogger(__name__)

__all__ = ["get_listing", "reset_robots_cache", "search_listings"]


# ── Public API ─────────────────────────────────────────────────────────
async def get_listing(zillow_id: str) -> dict[str, Any]:
    """Look up a single Zillow listing by its zpid. Never raises.

    Primary source is the Zillow homedetails page's embedded ``__NEXT_DATA__``
    JSON. When Zillow is unreachable or unparsable the guarded fallback chain
    runs: Redfin home-detail endpoint, then (best-effort, usually 404)
    Apartments.com and Zumper by id. Returns ``{}`` on any failure.
    """
    try:
        return await _get_listing(zillow_id)
    except Exception:
        logger.exception("real_estate_get_listing_crashed")
        return {}


async def _get_listing(zillow_id: str) -> dict[str, Any]:
    listing_url = f"{ZILLOW_BASE}/homedetails/{zillow_id}_zpid/"
    html = await _fetch_page(listing_url)
    if html is None:
        return await _listing_fallbacks(zillow_id)
    data = _extract_next_data(html)
    if data is None:
        return await _listing_fallbacks(zillow_id)
    record = _parse_zillow_listing(data, listing_url)
    if not record.get("address") and record.get("price") is None:
        return await _listing_fallbacks(zillow_id)
    return record


async def _listing_fallbacks(zillow_id: str) -> dict[str, Any]:
    """Guarded single-listing fallback chain: Redfin -> Apartments -> Zumper.

    The Apartments.com / Zumper lookups treat ``zillow_id`` as the listing id
    on those sites; like the Redfin path lookup they are best-effort and
    usually 404 for a Zillow-only id. Each step never raises.
    """
    redfin = await _redfin_listing_fallback(zillow_id)
    if redfin:
        return redfin
    apartments = await _apartments_listing_fallback(zillow_id)
    if apartments:
        return apartments
    return await _zumper_listing_fallback(zillow_id)


async def search_listings(
    location: str, status: str = "for_sale", limit: int = 20
) -> list[dict[str, Any]]:
    """Search listings for a location. Never raises; ``[]`` on failure.

    Fallback chain: Zillow SRP page (embedded ``__NEXT_DATA__``) -> Redfin
    GIS API -> Apartments.com (``for_rent`` only, embedded
    ``__PRELOADED_STATE__``) -> Zumper (``for_rent`` only, embedded
    ``__NUXT__``). ``status`` is one of ``for_sale`` / ``for_rent`` / ``sold``.
    """
    try:
        return await _search_listings(location, status, limit)
    except Exception:
        logger.exception("real_estate_search_listings_crashed")
        return []


async def _search_listings(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    if status not in _REDFIN_STATUS_CODES:
        logger.warning("real_estate_unknown_status", extra={"status": status})
        status = "for_sale"
    limit = max(1, min(50, int(limit)))
    zillow_results = await _search_zillow(location, status, limit)
    if zillow_results:
        return zillow_results
    redfin_results = await _search_redfin(location, status, limit)
    if redfin_results:
        return redfin_results
    # Apartments.com and Zumper are rental-only sources: only consulted for
    # for_rent searches, so for_sale/sold never hit the rental chain.
    if status != "for_rent":
        return []
    apartments_results = await _search_apartments(location, limit)
    if apartments_results:
        return apartments_results
    return await _search_zumper(location, limit)
