"""Local business data package — Google Maps / Yelp listings + reviews.

Lead-generation data for Pry: local business listings (Google Maps search),
place detail with popular times, and full review history (Google Maps +
Yelp) that goes beyond the 5-review API cap.

Public functions (all async, never raise — they return ``[]`` / ``{}``
on any failure):

* :func:`local_data.places.search_places` — Google Maps business search
* :func:`local_data.places.get_place` — place detail + popular times
* :func:`local_data.reviews.get_reviews` — Google Maps / Yelp reviews

Example:
    >>> from local_data import get_place, get_reviews, search_places
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from local_data.places import get_place, search_places
from local_data.reviews import get_reviews

__all__ = ["get_place", "get_reviews", "search_places"]

# ── Re-export public callables from sibling submodules ───────────────────
# Mirrors crypto_market/__init__.py: any sibling module created later (for
# example by a parallel agent) has its public callables re-exported here so
# consumers can import them from the package root. Names already in
# __all__ are never overwritten, so the canonical interface stays stable.
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_") or _module_info.name in ("places", "reviews"):
        continue
    _mod = importlib.import_module(f"{__name__}.{_module_info.name}")
    for _attr in dir(_mod):
        if _attr.startswith("_") or _attr in __all__:
            continue
        _obj = getattr(_mod, _attr)
        if callable(_obj) and str(getattr(_obj, "__module__", "")).startswith(__name__):
            globals()[_attr] = _obj
            __all__.append(_attr)
