"""Government data package — procurement + product recalls for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`gov_data.procurement` — SAM.gov Opportunities (federal procurement
  solicitations, free no-auth API with a free API key via ``PRY_SAM_API_KEY``).
* :mod:`gov_data.recalls` — CPSC product recalls + FDA openFDA enforcement
  (recalls), free public APIs, no auth.

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just ``procurement`` and
``recalls``.

Example:
    >>> from gov_data import search_opportunities, search_recalls
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from datasets.gov_data.procurement import get_opportunity, search_opportunities
from datasets.gov_data.recalls import get_recall, search_recalls

__all__ = [
    "get_opportunity",
    "get_recall",
    "search_opportunities",
    "search_recalls",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose "the 2 modules' public
# functions". procurement and recalls (owned by this agent) are imported
# statically above; any sibling modules created in parallel (e.g. by other
# agents) are imported and their public callables re-exported here. Names
# already in __all__ are never overwritten, so the canonical interface stays
# stable.
_STATIC_MODULES = ("procurement", "recalls")
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
