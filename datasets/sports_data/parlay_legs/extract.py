"""Compatibility exports for parlay-leg extraction helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from .extract_market import _comparison_team_names, _market_legs_from_outcomes
from .extract_props import _prop_legs_from_records

__all__ = [
    "_comparison_team_names",
    "_market_legs_from_outcomes",
    "_prop_legs_from_records",
]
