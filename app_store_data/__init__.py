"""App-store intelligence package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`app_store_data.apple` — Apple App Store via the iTunes Search API
  (free, no auth) and the iTunes customer-reviews RSS feed: app search,
  app lookup, recent reviews.
* :mod:`app_store_data.google_play` — Google Play via store-page scraping
  (``__NEXT_DATA__`` embedded JSON + ``AF_initDataCallback``): app search,
  app details, recent reviews. Anti-bot is detected and flagged.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes.

Example:
    >>> from app_store_data import (
    ...     apple_search, google_play_search, play_details, reviews_for_app,
    ... )
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from app_store_data.apple import get_app_details, get_reviews, search_apps as apple_search
from app_store_data.google_play import (
    get_app_details as play_details,
    get_reviews as play_reviews,
    search_apps as google_play_search,
)

__all__ = [
    "apple_search",
    "get_app_details",
    "get_reviews",
    "google_play_search",
    "play_details",
    "play_reviews",
]
