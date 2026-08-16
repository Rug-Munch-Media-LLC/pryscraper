"""Bidding data package — government contracts + grants for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`bidding_data.contracts` — contract solicitations + awards merged
  across SAM.gov (federal), TED (EU), NY Contract Reporter (state) and
  FedConnect (best-effort). Free sources, no auth beyond the optional free
  SAM.gov key (``PRY_SAM_API_KEY``).
* :mod:`bidding_data.grants` — federal grant opportunities from the free
  Grants.gov GrantsWS REST API (no auth).

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just ``contracts`` and
``grants``.

Example:
    >>> from bidding_data import search_contracts, search_grants
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from bidding_data.contracts import get_contract, search_contracts
from bidding_data.grants import get_grant, search_grants

__all__ = [
    "get_contract",
    "get_grant",
    "search_contracts",
    "search_grants",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose the public functions of the
# bidding_data submodules. contracts and grants (owned by this agent) are
# imported statically above; any sibling modules created in parallel (e.g.
# forecasts, awards) are imported and their public callables re-exported
# here. Names already in __all__ are never overwritten, so the canonical
# interface stays stable.
_STATIC_MODULES = ("contracts", "grants")
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
