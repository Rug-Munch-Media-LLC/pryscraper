"""Grocery prices by ZIP — Kroger API + store-scrape fallbacks.

Four free sources are aggregated in fallback order (a source is only
consulted when every earlier one returned nothing, so one store down never
empties the answer):

* **Kroger API** (:mod:`datasets.food_data.grocery_kroger`) — the
  market-standard grocery product + pricing API. Requires **free** OAuth2
  client credentials (https://developer.kroger.com) via the
  ``PRY_KROGER_CLIENT_ID`` and ``PRY_KROGER_CLIENT_SECRET`` env vars.
* **Walmart store scrape** (:mod:`datasets.food_data.grocery_walmart`) —
  no key, no quota; REDUX JSON extraction, best-effort.
* **Instacart store scrape** (:mod:`datasets.food_data.grocery_instacart`)
  — no key; Apollo state + JSON-LD extraction, best-effort.
* **Aldi / regional store scrape** (:mod:`datasets.food_data.grocery_aldi`)
  — no key; JSON-LD offers, best-effort.

Contract
--------
* :func:`get_grocery_prices` — async, never raises, returns a ``list``
  (``[]`` on failure). One record per (product, store).

Result shape::

    {
        "product": "Galaxy 9, 22 oz",
        "store": "Kroger",
        "price": 3.49,
        "currency": "USD",
        "zip_code": "45202",
        "unit": "1 LB",
        "date": "2026-08-16",
    }

``unit`` is the retailer's size/sold-by string ("1 LB", "2 L", "each")
or ``"each"`` when unknown. ``date`` is the UTC date the price was
observed.

Anti-bot honesty: scraping sources are parsed with signature-based
extractors over embedded JSON, mirroring the travel/commerce modules'
approach. When a site changes layout or blocks the request, output
silently degrades to ``[]`` — never an exception.

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
from typing import Any

from datasets.food_data.grocery_aldi import _aldi_prices
from datasets.food_data.grocery_common import _EXCLUDED_EXCEPTIONS, _valid_zip
from datasets.food_data.grocery_instacart import _instacart_prices
from datasets.food_data.grocery_kroger import (  # noqa: F401
    _clear_token_cache,
    _kroger_prices,
)
from datasets.food_data.grocery_walmart import _walmart_prices

logger = logging.getLogger(__name__)

__all__ = ["get_grocery_prices"]


async def get_grocery_prices(query: str, zip_code: str, limit: int = 20) -> list[dict[str, Any]]:
    """Grocery prices by ZIP. Async, never raises, ``[]`` on failure.

    Sources are tried in fallback order (Kroger → Walmart → Instacart →
    Aldi): the first source that returns any records wins, so one store
    being down never empties the answer. Kroger is only used when
    ``PRY_KROGER_CLIENT_ID`` / ``PRY_KROGER_CLIENT_SECRET`` are configured;
    the remaining three are keyless best-effort store scrapes.
    """
    query = (query or "").strip()
    zip_code = (zip_code or "").strip()
    if not query or not _valid_zip(zip_code) or limit <= 0:
        return []
    sources: tuple[tuple[Any, str], ...] = (
        (_kroger_prices, "grocery_kroger_failed"),
        (_walmart_prices, "grocery_walmart_failed"),
        (_instacart_prices, "grocery_instacart_failed"),
        (_aldi_prices, "grocery_aldi_failed"),
    )
    for fetcher, failure_key in sources:
        try:
            results = await fetcher(query, zip_code, limit)
            if results:
                return results[:limit]
        except _EXCLUDED_EXCEPTIONS as exc:
            logger.warning(failure_key, extra={"error": str(exc)[:120]})
    return []
