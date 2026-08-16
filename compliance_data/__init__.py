"""Regulatory & compliance data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`compliance_data.enforcement` — FDA / FTC / CFPB / SEC enforcement
  actions and consumer complaints (free, no-auth public sources) for
  regulatory / compliance screening workflows.

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just ``enforcement``.

Example:
    >>> from compliance_data import search_enforcement, watch_company
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from compliance_data.enforcement import get_action, search_enforcement, watch_company

__all__ = [
    "get_action",
    "search_enforcement",
    "watch_company",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose the enforcement module's
# public functions (owned by this agent). Those are imported statically
# above; any sibling modules created in parallel (e.g. by other agents) are
# imported and their public callables re-exported here. Names already in
# __all__ are never overwritten, so the canonical interface stays stable.
_STATIC_MODULES = ("enforcement",)
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
