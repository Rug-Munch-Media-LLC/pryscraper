"""IP data package — patents, trademarks, and company-registry intelligence for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`ip_data.patents` — patent search/detail via Google Patents' free
  XHR query JSON API (no auth).
* :mod:`ip_data.trademarks` — US trademark search/detail via USPTO's free
  Trademark Search / TSDR JSON APIs (optional free API key).
* :mod:`ip_data.company_registry` — company registry search/detail via
  state Secretary of State public JSON search (Nevada built in; state
  configurable).

Every public function is async and never raises — failures degrade to
``[]`` / ``{}`` / ``None`` so consumers always get a safe value.

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just ``patents``.

Example:
    >>> from ip_data import search_companies, search_patents, search_trademarks
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from ip_data.patents import (
    get_patent,
    search_patents,
)

__all__ = [
    "get_patent",
    "search_patents",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose the public functions of
# every module in this package. patents (owned by this agent) is imported
# statically above; any sibling modules created in parallel (e.g. by other
# agents) are imported and their public callables re-exported here. Names
# already in __all__ are never overwritten, so the canonical interface
# stays stable.
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_") or _module_info.name == "patents":
        continue
    _mod = importlib.import_module(f"{__name__}.{_module_info.name}")
    for _attr in dir(_mod):
        if _attr.startswith("_") or _attr in __all__:
            continue
        _obj = getattr(_mod, _attr)
        if callable(_obj) and str(getattr(_obj, "__module__", "")).startswith(__name__):
            globals()[_attr] = _obj
            __all__.append(_attr)
