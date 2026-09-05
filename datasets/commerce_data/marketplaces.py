"""Commerce long-tail product search/lookup: eBay, Etsy, AliExpress, Shopify.

Thin facade re-exporting the focused marketplace modules (each carries
its own source notes and reliability caveats):

* :mod:`marketplaces_common` — shared pure parsing/coercion helpers.
* :mod:`marketplaces_http` — bounded-retry HTTP fetch layer.
* :mod:`marketplaces_ebay` — eBay Finding/Shopping API (free app key
  ``PRY_EBAY_API_KEY``; degrades to ``[]`` / ``{}`` without a key).
* :mod:`marketplaces_shopify` — public ``products.json`` endpoint
  (no auth, capped at 250 products per page).
* :mod:`marketplaces_etsy` — best-effort scraping of ``__NEXT_DATA__`` /
  JSON-LD (Etsy aggressively blocks datacenter traffic).
* :mod:`marketplaces_aliexpress` — best-effort extraction from embedded
  ``window._dida_config_`` / ``window.runParams`` JSON.
* :mod:`marketplaces_retail` — Target / Best Buy via marketplace.retail.

Contract
--------
* :func:`search_product` — async, never raises, returns a ``list``
  (``[]`` on failure).
* :func:`get_product` — async, never raises, returns a ``dict``
  (``{}`` on failure).

Canonical result shape::

    {
        "id": str,
        "title": str,
        "price": float | None,
        "currency": str | None,
        "seller": str | None,
        "rating": float | None,   # seller feedback score (eBay); None elsewhere
        "url": str,
        "marketplace": "ebay" | "etsy" | "aliexpress" | "shopify" | "target" | "bestbuy",
    }

Anti-bot honesty: scraping sources are parsed with signature-based
extractors over embedded JSON, mirroring the travel module's approach.
When a site changes layout or blocks the request, output silently
degrades to ``[]`` / ``{}`` — never an exception.

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
import os
from typing import Any

from datasets.commerce_data.marketplaces_aliexpress import (
    _aliexpress_get,
    _aliexpress_search,
)
from datasets.commerce_data.marketplaces_common import (  # noqa: F401
    _RETAIL_MARKETPLACES,
    MARKETPLACES,
    _clamp_limit,
)
from datasets.commerce_data.marketplaces_ebay import _ebay_get, _ebay_search
from datasets.commerce_data.marketplaces_etsy import _etsy_get, _etsy_search
from datasets.commerce_data.marketplaces_retail import _retail_get, _retail_search
from datasets.commerce_data.marketplaces_shopify import _shopify_get, _shopify_search

# Backoff tuning (tests monkeypatch these to 0 for speed). Owned here so
# marketplaces_http reads them lazily at call time via _retry_knobs().
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

_EBAY_API_KEY_ENV = "PRY_EBAY_API_KEY"

logger = logging.getLogger(__name__)


def _api_key() -> str:
    """Return the configured eBay app key, or '' when missing."""
    return os.environ.get(_EBAY_API_KEY_ENV, "").strip()


async def search_product(
    query: str, marketplace: str = "ebay", limit: int = 20
) -> list[dict[str, Any]]:
    """Search products across a marketplace. Async, never raises.

    ``marketplace`` is one of ``ebay``, ``etsy``, ``aliexpress``,
    ``shopify``, ``target``, ``bestbuy``.
    For ``shopify``, ``query`` is the store subdomain (e.g. ``"allbirds"``).

    Returns ``[]`` on any failure (missing API key, HTTP error, parse
    failure, unsupported marketplace, empty query).
    """
    text = (query or "").strip()
    mp = (marketplace or "").strip().lower()
    bounded = _clamp_limit(limit)
    if not text:
        return []
    if mp == "ebay":
        return await _ebay_search(text, bounded)
    if mp == "shopify":
        return await _shopify_search(text, bounded)
    if mp == "etsy":
        return await _etsy_search(text, bounded)
    if mp == "aliexpress":
        return await _aliexpress_search(text, bounded)
    if mp in _RETAIL_MARKETPLACES:
        return await _retail_search(mp, text, bounded)
    logger.warning("commerce_marketplace_unknown", extra={"marketplace": mp})
    return []


async def get_product(product_id: str, marketplace: str = "ebay") -> dict[str, Any]:
    """Fetch one product by id. Async, never raises.

    ``marketplace`` is one of ``ebay``, ``etsy``, ``aliexpress``,
    ``shopify``, ``target``, ``bestbuy``.
    For ``shopify``, ``product_id`` must be ``"store:id"`` or
    ``"store:handle"`` (e.g. ``"allbirds:123456789"``) because the public
    products.json endpoint needs the store to know where to look.

    Returns ``{}`` on any failure (missing API key, HTTP error, parse
    failure, unsupported marketplace, empty id, not found).
    """
    text = (product_id or "").strip()
    mp = (marketplace or "").strip().lower()
    if not text:
        return {}
    if mp == "ebay":
        return await _ebay_get(text)
    if mp == "shopify":
        return await _shopify_get(text)
    if mp == "etsy":
        return await _etsy_get(text)
    if mp == "aliexpress":
        return await _aliexpress_get(text)
    if mp in _RETAIL_MARKETPLACES:
        return await _retail_get(mp, text)
    logger.warning("commerce_marketplace_unknown", extra={"marketplace": mp})
    return {}
