"""Pry — travel hotels: hotel rate lookups (Google Hotels + Booking + Kayak + Expedia).

There is no free, keyless hotel-rate API, so this module scrapes four public
search pages in a guarded fallback chain:

* Google Hotels (primary) — ``https://www.google.com/travel/hotels`` with
  ``q``/``check_in``/``check_out`` params; rates are read from the embedded
  ``AF_initDataCallback`` JSON (same infrastructure as :mod:`travel.flights`).
* Booking.com (fallback 2) — ``https://www.booking.com/searchresults.html``
  with ``ss``/``checkin``/``checkout`` params; rates are read from embedded
  ``data-capla-trace`` JSON blocks, with a light regex fallback on the raw
  HTML when the JSON blocks are absent.
* Kayak (fallback 3) — ``https://www.kayak.com/hotels/{query}/{checkin}/
  {checkout}/2adults``; rates are read from the embedded
  ``window.__INITIAL_STATE__`` JSON via a string-aware balanced-brace scan.
* Expedia (fallback 4) — ``https://www.expedia.com/Hotel-Search`` with
  ``destination``/``checkInDate``/``checkOutDate`` params; rates are read
  from the page's ``application/ld+json`` structured-data blocks.

The chain is sequential: each source is only fetched when the previous one
yielded no rates, which keeps rate-limit pressure bounded.

Contract
--------
* async, never raise
* ``get_hotel_rates(hotel_name, checkin, checkout) -> dict`` with shape
  ``{"hotel", "rates": [{"site", "price_per_night", "currency", "total"}],
  "availability"}`` — ``availability`` is ``"available"`` when at least one
  rate was found, ``"unavailable"`` when a page was fetched but yielded no
  rates, ``"unknown"`` when nothing could be fetched. ``total`` may be
  absent (``None``) when the source only exposes a per-night price. Rates
  are aggregated per source site (cheapest per site).

Reliability (read before shipping)
----------------------------------
Google Hotels embeds its results as the same drifting, unversioned
``AF_initDataCallback`` JSON as Flights; Booking.com's ``data-capla-trace``
blocks are obfuscated and change regularly; Kayak's ``__INITIAL_STATE__``
and Expedia's JSON-LD are also layout-coupled and best-effort. Extraction is
signature-based and best-effort: layout changes degrade to ``{}``/empty
rates, never an exception. All four sources rate-limit / bot-guard page
hits — keep lookups bounded and respect the backoff knobs. Expedia in
particular frequently serves a bot/consent wall instead of results; treat
output as estimates.

Implementation is split across focused modules:

* :mod:`hotels_common` — shared fetching/validation/extraction helpers
* :mod:`hotels_google` — Google Hotels extraction
* :mod:`hotels_booking` — Booking.com extraction
* :mod:`hotels_kayak` — Kayak extraction
* :mod:`hotels_expedia` — Expedia extraction

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from datasets.travel.flights import _extract_af_callbacks
from datasets.travel.hotels_booking import _find_booking_rates
from datasets.travel.hotels_common import (
    _aggregate_site_rates,
    _empty_result,
    _fetch_page,
    _valid_date,
)
from datasets.travel.hotels_expedia import _extract_json_ld, _find_expedia_rates
from datasets.travel.hotels_google import _find_google_rates
from datasets.travel.hotels_kayak import (
    _extract_embedded_object,
    _find_kayak_rates,
    _kayak_search_url,
)

_BOOKING_URL = "https://www.booking.com/searchresults.html"
_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"
_GOOGLE_URL = "https://www.google.com/travel/hotels"


async def get_hotel_rates(hotel_name: str, checkin: str, checkout: str) -> dict[str, Any]:
    """Look up per-night rates for ``hotel_name`` between two dates.

    Args:
        hotel_name: Free-text hotel name / location query.
        checkin: Check-in date as ``YYYY-MM-DD``.
        checkout: Check-out date as ``YYYY-MM-DD``.

    Returns:
        ``{"hotel", "rates": [{"site", "price_per_night", "currency",
        "total"}], "availability"}``. Rates are aggregated per source site
        (cheapest per site). The fallback chain is sequential — Google Hotels
        -> Booking.com -> Kayak -> Expedia — each source fetched only when
        the previous one yielded no rates. Never raises.
    """
    name = hotel_name.strip() if isinstance(hotel_name, str) else ""
    if not name or not _valid_date(checkin) or not _valid_date(checkout):
        return _empty_result(name, "unknown")

    fetched_any = False
    rates_by_site: dict[str, dict[str, Any]] = {}

    # 1. Primary: Google Hotels.
    google_html = await _fetch_page(
        _GOOGLE_URL,
        {
            "q": name,
            "check_in": checkin,
            "check_out": checkout,
            "hl": "en",
            "gl": "us",
        },
    )
    if google_html:
        fetched_any = True
        for callback in _extract_af_callbacks(google_html):
            for entry in _find_google_rates(callback.get("data")):
                _aggregate_site_rates(rates_by_site, "google", entry)

    # 2. Booking.com (only if Google yielded nothing).
    if "google" not in rates_by_site:
        booking_html = await _fetch_page(
            _BOOKING_URL,
            {
                "ss": name,
                "checkin": checkin,
                "checkout": checkout,
                "group_adults": "2",
                "no_rooms": "1",
                "lang": "en-us",
                "selected_currency": "USD",
            },
        )
        if booking_html:
            fetched_any = True
            for entry in _find_booking_rates(booking_html):
                _aggregate_site_rates(rates_by_site, "booking", entry)

    # 3. Kayak (embedded __INITIAL_STATE__ JSON).
    if not rates_by_site:
        kayak_html = await _fetch_page(_kayak_search_url(name, checkin, checkout), {})
        if kayak_html:
            fetched_any = True
            state = _extract_embedded_object(kayak_html, "window.__INITIAL_STATE__")
            for entry in _find_kayak_rates(state):
                _aggregate_site_rates(rates_by_site, "kayak", entry)

    # 4. Expedia (JSON-LD structured data).
    if not rates_by_site:
        expedia_html = await _fetch_page(
            _EXPEDIA_URL,
            {
                "destination": name,
                "checkInDate": checkin,
                "checkOutDate": checkout,
                "adults": "2",
                "rooms": "1",
            },
        )
        if expedia_html:
            fetched_any = True
            for entry in _find_expedia_rates(expedia_html):
                _aggregate_site_rates(rates_by_site, "expedia", entry)

    rates = sorted(rates_by_site.values(), key=lambda entry: entry["site"])
    if rates:
        return {"hotel": name, "rates": rates, "availability": "available"}
    if fetched_any:
        return _empty_result(name, "unavailable")
    return _empty_result(name, "unknown")


# Re-exports for backward compatibility (tests import via ``hotels.<symbol>``).
__all__ = [
    "_extract_embedded_object",
    "_extract_json_ld",
    "_find_booking_rates",
    "_find_expedia_rates",
    "_find_google_rates",
    "_find_kayak_rates",
    "get_hotel_rates",
]
