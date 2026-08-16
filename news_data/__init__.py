"""News headlines + sentiment data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints, trading/PR alert bots) can
import them from a single place:

* :mod:`news_data.headlines` — real-time headlines from the free, no-auth
  GDELT DOC 2.0 API (``mode=artlist`` JSON) with a GDELT RSS fallback;
  plus full-article extraction (text, summary, keywords, authors) that
  reuses Pry's own anti-detection scraper.
* :mod:`news_data.sentiment` — aggregate sentiment for a query
  (GDELT ``Tone`` compound score, with a lightweight keyword-based
  fallback) and per-day entity timelines with top sources.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure (missing key, network, quota, malformed payload).
See each module's docstring for exact result shapes.

Example:
    >>> from news_data import get_headlines, get_sentiment, get_entity_timeline
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from news_data.headlines import get_article, get_headlines
from news_data.sentiment import get_entity_timeline, get_sentiment

__all__ = [
    "get_article",
    "get_entity_timeline",
    "get_headlines",
    "get_sentiment",
]
