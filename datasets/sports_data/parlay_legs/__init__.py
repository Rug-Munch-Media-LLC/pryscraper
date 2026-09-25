"""Stable facade for same-game parlay leg extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datasets.sports_data.parlay_math import _correlated

from .extract import (
    _comparison_team_names,
    _market_legs_from_outcomes,
    _prop_legs_from_records,
)
from .fair import _facade, _fair_probability, _market_anchor_fair
from .scan import _scan_pool
from .select import (
    _best_leg_pool,
    _combo_book,
    _different_class,
    _leg_identity,
)

_ANCHORED_MARKETS = frozenset({"h2h", "spread", "total"})
_MAX_POOL_LEGS = 40
_MAX_COMBOS = 600

__all__ = [
    "_ANCHORED_MARKETS",
    "_MAX_COMBOS",
    "_MAX_POOL_LEGS",
    "_best_leg_pool",
    "_combo_book",
    "_comparison_team_names",
    "_correlated",
    "_different_class",
    "_facade",
    "_fair_probability",
    "_leg_identity",
    "_market_anchor_fair",
    "_market_legs_from_outcomes",
    "_prop_legs_from_records",
    "_scan_pool",
]
