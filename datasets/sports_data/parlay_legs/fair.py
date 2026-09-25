"""Fair-probability helpers for same-game parlay leg extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import math
from typing import Any

_ANCHORED_MARKETS = frozenset({"h2h", "spread", "total"})


def _facade() -> Any:
    """Late-bound facade module (keeps guarded imports monkeypatchable)."""
    import datasets.sports_data.parlays as m

    return m


def _fair_probability(
    side_price: float, odds_a: float | None, odds_b: float | None
) -> float | None:
    """Return the no-vig probability for one side of a priced market.

    Invalid or non-finite prices fail closed. Valid legacy calculations keep
    the same rounding and raw-implied fallback behavior.
    """
    try:
        side = float(side_price)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(side) or side <= 1.0:
        return None
    if odds_a is None or odds_b is None:
        return round(1.0 / side, 6)
    try:
        odds_a_value = float(odds_a)
        odds_b_value = float(odds_b)
    except (TypeError, ValueError, OverflowError):
        return round(1.0 / side, 6)
    if (
        not math.isfinite(odds_a_value)
        or not math.isfinite(odds_b_value)
        or odds_a_value <= 1.0
        or odds_b_value <= 1.0
    ):
        return round(1.0 / side, 6)
    compute_no_vig = _facade()._compute_no_vig
    if compute_no_vig is not None:
        try:
            fair = compute_no_vig(odds_a_value, odds_b_value)
        except Exception:  # noqa: BLE001 - helper contract is never-raise
            fair = {}
        if isinstance(fair, dict):
            prob_a = fair.get("home_prob")
            prob_b = fair.get("away_prob")
            if isinstance(prob_a, (int, float)) and math.isfinite(prob_a) and side == odds_a_value:
                return round(float(prob_a), 6)
            if isinstance(prob_b, (int, float)) and math.isfinite(prob_b) and side == odds_b_value:
                return round(float(prob_b), 6)
    return round(1.0 / side, 6)


def _market_anchor_fair(
    legs_by_market: dict[str, list[dict[str, Any]]], market: str
) -> dict[str, float]:
    """Fair probabilities from the sharpest finite, lower-margin book."""
    legs = legs_by_market.get(market, [])
    by_book: dict[str, list[dict[str, Any]]] = {}
    for leg in legs:
        by_book.setdefault(str(leg.get("book") or "unknown"), []).append(leg)
    best_margin: float | None = None
    best_fair: dict[str, float] = {}
    for _book, book_legs in by_book.items():
        sides: dict[str, float] = {}
        for leg in book_legs:
            side = str(leg.get("side") or "").strip().lower()
            if not side or side in sides:
                continue
            try:
                odds = float(leg["odds"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(odds) or odds <= 1.0:
                continue
            sides[side] = odds
        if len(sides) < 2:
            continue
        compute_no_vig = getattr(_facade(), "_compute_no_vig", None)
        if compute_no_vig is None:
            continue
        side_keys = list(sides)
        try:
            fair = compute_no_vig(sides[side_keys[0]], sides[side_keys[1]])
        except Exception:  # noqa: BLE001 - helper contract is never-raise
            fair = {}
        if not isinstance(fair, dict):
            continue
        margin = fair.get("margin")
        prob_a = fair.get("home_prob")
        prob_b = fair.get("away_prob")
        if not isinstance(margin, (int, float)) or not isinstance(prob_a, (int, float)):
            continue
        if not isinstance(prob_b, (int, float)):
            continue
        if not all(math.isfinite(value) for value in (margin, prob_a, prob_b)):
            continue
        if best_margin is None or float(margin) < best_margin:
            best_margin = float(margin)
            best_fair = {
                side_keys[0]: round(float(prob_a), 6),
                side_keys[1]: round(float(prob_b), 6),
            }
    return best_fair
