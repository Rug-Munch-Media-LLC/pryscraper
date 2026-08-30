"""Crypto market package — token-launch detection for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`crypto_market.token_launches` — new token / new pair / trending
  detection built on free public APIs (DexScreener, CoinGecko, DefiLlama).

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just
``token_launches``.

Example:
    >>> from crypto_market import get_new_tokens, get_trending_tokens
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from crypto_market.kol_leaderboards import (
    KOL_SOURCES,
    fetch_kol_leaderboards,
    fetch_kolscan_leaderboard,
    health_check,
    source_health,
)
from crypto_market.token_launches import (
    get_chain_context,
    get_new_pairs,
    get_new_tokens,
    get_trending_tokens,
)

__all__ = [
    "KOL_SOURCES",
    "fetch_kol_leaderboards",
    "fetch_kolscan_leaderboard",
    "get_chain_context",
    "get_new_pairs",
    "get_new_tokens",
    "get_trending_tokens",
    "health_check",
    "source_health",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose "the 3 modules' public
# functions". token_launches (owned by this agent) is imported statically
# above; any sibling modules created in parallel (e.g. by other agents) are
# imported and their public callables re-exported here. Names already in
# __all__ are never overwritten, so the canonical interface stays stable.
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_") or _module_info.name == "token_launches":
        continue
    _mod = importlib.import_module(f"{__name__}.{_module_info.name}")
    for _attr in dir(_mod):
        if _attr.startswith("_") or _attr in __all__:
            continue
        _obj = getattr(_mod, _attr)
        if callable(_obj) and str(getattr(_obj, "__module__", "")).startswith(__name__):
            globals()[_attr] = _obj
            __all__.append(_attr)
