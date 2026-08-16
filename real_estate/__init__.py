"""Real-estate package — listings + county property records for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`real_estate.listings` — Zillow ``__NEXT_DATA__`` page parsing with a
  Redfin ``/stingray/api/gis`` fallback (free, no keys).
* :mod:`real_estate.property_records` — county assessor property records via
  public ArcGIS REST FeatureServer endpoints (free, no keys).

All functions are async and never raise — they return ``{}`` / ``[]`` on
failure. See each module's docstring for the exact result shapes and the
robots.txt / backoff policy.

Example:
    >>> from real_estate import get_listing, search_listings, get_property
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from real_estate.listings import get_listing, search_listings
from real_estate.property_records import get_property

__all__ = [
    "get_listing",
    "get_property",
    "search_listings",
]
