"""Marketplace intelligence scrapers — Amazon, Walmart, TikTok Shop.

This package provides free-tier, keyless product intelligence for the three
highest-revenue marketplace niches:

* :mod:`marketplace.amazon` — Amazon product detail + search via the public
  product/search HTML pages (no API key; optional Rainforest free-tier key
  is read from the environment when present).
* :mod:`marketplace.walmart` — Walmart product detail + search via the
  ``__NEXT_DATA__`` JSON embedded in the public product/search pages.
* :mod:`marketplace.tiktok_shop` — TikTok Shop product detail via the
  unauthenticated web render endpoint, plus a best-effort trending list.

Public functions (imported per module so the identical names on different
providers never collide):

====================  ===========================================
``amazon.get_product(asin)``            → dict
``amazon.search_products(query, limit)``→ list[dict]
``walmart.get_product(product_id)``     → dict
``walmart.search_products(query, limit)``→ list[dict]
``tiktok_shop.get_product(product_id)`` → dict
``tiktok_shop.get_trending(limit)``     → list[dict]
====================  ===========================================

For convenience this package also re-exports every public function with an
unambiguous provider prefix (``amazon_get_product``, ``walmart_search_products``,
…), which is the recommended import for the MCP / REST wiring layer::

    from pry.commerce.marketplace import amazon_get_product, walmart_get_product

Contracts:

* **Never raise.** Every public function catches provider/transport/parse
  failures and returns ``{}`` (single product) or ``[]`` (lists) instead.
* **No secrets.** Optional API keys (e.g. ``RAINFOREST_API_KEY`` /
  ``PRY_RAINFOREST_API_KEY``) are read from the environment at call time —
  never hardcoded.
* **Free tier.** Direct scraping of public HTML / embedded JSON by default;
  a Rainforest API key (free tier) is only consulted when scraping fails.

Configuration (env vars, all optional):

* ``PRY_MARKETPLACE_USER_AGENT`` — fixed UA override (default: rotate).
* ``PRY_MARKETPLACE_HONOR_ROBOTS`` — "1" (default) fetches + honors each
  host's robots.txt before requesting product/search pages; set to "0" to
  bypass (needed if a retailer disallows product paths).
* ``PRY_MARKETPLACE_HTTP_RETRIES`` — retries per request (default 2).
* ``PRY_RAINFOREST_API_KEY`` / ``RAINFOREST_API_KEY`` — optional Rainforest
  free-tier key used as an Amazon fallback.
* ``PRY_TIKTOK_TRENDING_PLACEHOLDER`` — "1" returns clearly-marked
  placeholder rows from :func:`tiktok_shop.get_trending` when the bestseller
  page cannot be scraped (default "0" → empty list).

Internal helpers (``_``-prefixed) live in :mod:`.config`, :mod:`.helpers`,
:mod:`.http` and :mod:`.rainforest`; they are re-exported here for
backward compatibility with the submodules and tests, but are not part
of the public API.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

# isort: off
# Internal helpers must load before the provider submodules, which import
# these names back from this package.
# ── Internal helpers re-exported for backward compatibility ────────────
from pry.commerce.marketplace.config import (  # noqa: F401
    HTTP_TIMEOUT,
    ROBOTS_TIMEOUT,
    _http_retries,
    _rotate_ua,
)
from pry.commerce.marketplace.helpers import (  # noqa: F401
    _find_redux_state,
    _find_script_json,
    _first_text,
    _is_amazon_block,
    _lxml_doc,
    _price_parts,
    _text,
    _to_float,
    _to_int,
)
from pry.commerce.marketplace.http import (  # noqa: F401
    _backoff,
    _clear_robots_cache,
    _fetch_html,
    _fetch_json,
    _fetch_robots,
    _robots_allowed,
    _robots_rules,
    _rule_matches,
)
from pry.commerce.marketplace.rainforest import (  # noqa: F401
    _amazon_via_rainforest,
    _rainforest_api_key,
)
from pry.commerce.marketplace.tiktok_shop import (
    get_product as tiktok_get_product,
    get_trending as tiktok_get_trending,
)
from pry.commerce.marketplace.walmart import (
    get_product as walmart_get_product,
    search_products as walmart_search_products,
)

# ── Public re-exports (provider-prefixed — names collide across modules) ──
from pry.commerce.marketplace.amazon import (
    get_product as amazon_get_product,
    search_products as amazon_search_products,
)

# isort: on

# Submodules stay importable so consumers can use the per-provider names
# directly: ``from pry.commerce.marketplace.amazon import get_product``.
__all__ = [
    "amazon_get_product",
    "amazon_search_products",
    "tiktok_get_product",
    "tiktok_get_trending",
    "walmart_get_product",
    "walmart_search_products",
]
