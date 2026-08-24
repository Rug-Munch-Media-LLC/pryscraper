"""Grocery prices + restaurant menus for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints, food-data clients) can import
them from a single place:

* :mod:`food_data.grocery` — grocery prices by ZIP (Kroger API with free
  OAuth client credentials via ``PRY_KROGER_CLIENT_ID`` /
  ``PRY_KROGER_CLIENT_SECRET``, Walmart store-scrape fallback).
* :mod:`food_data.restaurants` — restaurant menus (menu-page JSON-LD
  extraction with an HTML price-scrape fallback; source pages found via
  DuckDuckGo HTML search, no key required).

All functions are async and never raise — they degrade to ``[]`` / ``{}``
on any failure (network, quota, malformed payload, invalid input), which
makes them safe for high-frequency pollers.

Example:
    >>> from food_data import get_grocery_prices, get_restaurant_menu
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from datasets.food_data.grocery import get_grocery_prices
from datasets.food_data.restaurants import get_restaurant_menu

__all__ = [
    "get_grocery_prices",
    "get_restaurant_menu",
]

# ── Re-export public callables from sibling submodules ───────────────────
# grocery and restaurants (owned by this agent) are imported statically
# above; any sibling modules created in parallel (e.g. by other agents) are
# imported and their public callables re-exported here. Names already in
# __all__ are never overwritten, so the canonical interface stays stable.
_STATIC_MODULES = ("grocery", "restaurants")
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_") or _module_info.name in _STATIC_MODULES:
        continue
    _mod = importlib.import_module(f"{__name__}.{_module_info.name}")
    for _attr in dir(_mod):
        if _attr.startswith("_") or _attr in __all__:
            continue
        _obj = getattr(_mod, _attr)
        if callable(_obj) and str(getattr(_obj, "__module__", "")).startswith(__name__):
            globals()[_attr] = _obj
            __all__.append(_attr)
