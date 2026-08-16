"""Sports + betting data package — live odds, player stats, scores for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints, betting-bot clients) can import
them from a single place:

* :mod:`sports_data.odds` — live betting odds from The Odds API (free tier,
  key via ``PRY_ODDS_API_KEY``) with an ESPN scoreboard fallback; plus
  multi-sportsbook odds comparison per event.
* :mod:`sports_data.stats` — player stats from ESPN public endpoints.
* :mod:`sports_data.scores` — scores from ESPN public scoreboards.

All functions are async and never raise — they degrade to ``[]`` / ``{}`` /
``None`` on any failure (network, quota, malformed payload, invalid sport),
which makes them safe for high-frequency pollers.

Example:
    >>> from sports_data import get_odds, get_event_odds, get_player_stats, get_scores
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from sports_data.odds import get_event_odds, get_odds
from sports_data.scores import get_scores
from sports_data.stats import get_player_stats

__all__ = [
    "get_event_odds",
    "get_odds",
    "get_player_stats",
    "get_scores",
]

# ── Re-export public callables from sibling submodules ───────────────────
# odds, scores and stats (owned by this agent) are imported statically
# above; any sibling modules created in parallel (e.g. by other agents) are
# imported and their public callables re-exported here. Names already in
# __all__ are never overwritten, so the canonical interface stays stable.
_STATIC_MODULES = ("odds", "scores", "stats")
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
