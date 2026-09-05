"""Deal-aggregator coupons: best-effort Slickdeals / RetailMeNot scrape.

Thin re-export facade — implementation lives in:

* :mod:`datasets.deals_data.coupons_common` — config, HTTP fetch, helpers,
  blocked-state registry.
* :mod:`datasets.deals_data.coupons_parsing` — JSON-LD / ``__NEXT_DATA__``
  / classic-HTML deal-record parsers.
* :mod:`datasets.deals_data.coupons_api` — public ``search_deals`` /
  ``get_store_deals`` orchestration.

Contract
--------
* :func:`search_deals` — async, never raises, returns a ``list`` of deal
  records (``[]`` on failure / anti-bot blocks).
* :func:`get_store_deals` — async, never raises, same record shape.
* :func:`blocked_sources` — sync, returns the list of sources that looked
  anti-bot-blocked during the most recent search/store call.

Canonical deal record:
``{id, title, store, discount, price, original_price, url, expires,
source}`` where ``discount`` is the percent saved (``float | None``),
``price`` / ``original_price`` are ``float | None`` and ``expires`` is an
ISO-ish string (``""`` when unknown).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.deals_data.coupons_api import get_store_deals, search_deals
from datasets.deals_data.coupons_common import (
    _BLOCKED,
    _LOCK,
    MAX_BACKOFF,
    MAX_RETRIES,
    RETRY_BASE,
    blocked_sources,
)

__all__ = [
    "MAX_BACKOFF",
    "MAX_RETRIES",
    "RETRY_BASE",
    "_BLOCKED",
    "_LOCK",
    "blocked_sources",
    "get_store_deals",
    "search_deals",
]
