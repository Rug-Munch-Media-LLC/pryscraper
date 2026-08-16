"""Event-tickets data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints, drop-alert bots) can import
them from a single place:

* :mod:`events_data.tickets` — Ticketmaster Discovery API event search /
  detail (free key ``PRY_TICKETMASTER_API_KEY``) with a JSON-LD page-scrape
  fallback; best-effort StubHub / SeatGeek resale-listing scrapes (both
  marketplaces are anti-bot protected — results honestly degrade to ``[]``);
  and an in-memory + optional-JSON (``PRY_TICKETS_HISTORY_JSON``) resale
  price-history tracker for drop-alert monitoring.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure (missing key, network, quota, malformed payload,
anti-bot block). See each module's docstring for exact result shapes.

Example:
    >>> from events_data import search_events, get_event, get_resale_prices
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from events_data.tickets import (
    get_event,
    get_price_history,
    get_resale_prices,
    record_price_snapshot,
    search_events,
)

__all__ = [
    "get_event",
    "get_price_history",
    "get_resale_prices",
    "record_price_snapshot",
    "search_events",
]
