"""Commerce long-tail + social data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`commerce_data.marketplaces` — product search/lookup across eBay
  (Finding API, free key ``PRY_EBAY_API_KEY``), Shopify (public
  ``products.json``, no auth), Etsy and AliExpress (best-effort page
  scraping — both are heavily anti-bot protected).
* :mod:`commerce_data.social` — public-profile social follower metrics
  for Instagram, TikTok, X/Twitter and YouTube, scraped from profile
  pages. All platforms serve login walls / JS challenges to datacenter
  IPs; results degrade to partial data (``None`` fields) rather than
  erroring.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes and the reliability caveats.

Example:
    >>> from commerce_data import get_social_metrics, search_product
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.commerce_data.marketplaces import get_product, search_product
from datasets.commerce_data.social import get_social_metrics

__all__ = [
    "get_product",
    "get_social_metrics",
    "search_product",
]
