"""Travel package — flights + hotel rates for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`travel.flights` — Google Flights scraping (no public API): cheap
  date grid + flight search, built on the public ``tfs`` deep-link page
  with protobuf-encoded search parameters and embedded ``AF_initDataCallback``
  JSON extraction.
* :mod:`travel.hotels` — hotel rate lookups via Google Hotels with a
  Booking.com fallback (both free, keyless page scraping).

All functions are async and never raise — they return ``{}`` / ``[]`` on
failure. See each module's docstring for the exact result shapes and the
reliability caveats (Google Flights/Hotels embedded JSON drifts over time;
treat output as best-effort).

Example:
    >>> from travel import search_flights, get_hotel_rates
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from travel.flights import cheapest_date_grid, search_flights
from travel.hotels import get_hotel_rates

__all__ = [
    "cheapest_date_grid",
    "get_hotel_rates",
    "search_flights",
]
