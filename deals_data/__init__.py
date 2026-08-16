"""Deals + drop-alerts data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints, deal bots) can import them
from a single place:

* :mod:`deals_data.coupons` — best-effort scrape of public deal
  aggregators (Slickdeals, RetailMeNot) using embedded JSON + JSON-LD
  blocks. Both sites sit behind anti-bot / JS challenges for datacenter
  traffic — results honestly degrade to ``[]`` and blocked sources are
  flagged via :func:`deals_data.coupons.blocked_sources`.
* :mod:`deals_data.drops` — in-memory (+ optional-JSON via
  ``PRY_DROPS_ALERTS_JSON``) product restock/price-drop alert tracker.
  Current prices are resolved through the repo's guarded
  ``marketplace.amazon`` module (ASIN lookup or keyword search), never
  raising on failure.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure (missing key, network, quota, malformed payload,
anti-bot block). See each module's docstring for exact result shapes.

Example:
    >>> from deals_data import search_deals, set_drop_alert, check_drop_alerts
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from deals_data.coupons import (
    blocked_sources,
    get_store_deals,
    search_deals,
)
from deals_data.drops import (
    check_drop_alerts,
    clear_alert,
    list_alerts,
    set_drop_alert,
)

__all__ = [
    "blocked_sources",
    "check_drop_alerts",
    "clear_alert",
    "get_store_deals",
    "list_alerts",
    "search_deals",
    "set_drop_alert",
]
