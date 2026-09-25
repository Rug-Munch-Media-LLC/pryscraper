"""Round-robin pricing math."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import itertools
import logging
from typing import Any

from .legs import _normalize_legs
from .odds_math import decimal_to_american, parlay_decimal

logger = logging.getLogger(__name__)


def price_round_robin(
    legs: list[dict[str, Any]], parlay_size: int = 2, max_risk: float = 100
) -> dict[str, Any]:
    """Price a round robin (all combinations of N legs from the selection).

    Args:
        legs: Leg dicts; every combination of ``parlay_size`` legs is priced.
        parlay_size: Legs per parlay (default 2).
        max_risk: Total budget, split equally across the parlays (default 100).

    Returns:
        Dict with ``num_parlays``, ``total_risk``, ``max_win``, ``min_win``
        and ``all_combinations`` — or ``{}`` when fewer than ``parlay_size``
        valid legs remain. Never raises.
    """
    try:
        return _price_round_robin(legs, parlay_size, max_risk)
    except Exception:
        logger.exception("sports_round_robin_price_crashed")
        return {}


def _price_round_robin(
    legs: list[dict[str, Any]], parlay_size: int, max_risk: float
) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    size = max(2, int(parlay_size if parlay_size is not None else 2))
    if len(normalized) < size:
        return {}
    combos = list(itertools.combinations(normalized, size))
    num_parlays = len(combos)
    budget = max(0.0, float(max_risk if max_risk is not None else 100))
    stake = round(budget / num_parlays, 2) if num_parlays else 0.0
    combinations: list[dict[str, Any]] = []
    profits: list[float] = []
    for combo in combos:
        decimal = parlay_decimal([float(leg["decimal_odds"]) for leg in combo])
        profit = round(stake * (decimal - 1.0), 2)
        profits.append(profit)
        combinations.append(
            {
                "legs": [str(leg["selection"]) for leg in combo],
                "combined_odds": {"decimal": decimal, "american": decimal_to_american(decimal)},
                "stake": stake,
                "profit": profit,
            }
        )
    # min_win = profit if exactly the worst single parlay wins (all others lose)
    min_win = min(profits) if profits else 0.0
    return {
        "bet_type": "round_robin",
        "parlay_size": size,
        "leg_count": len(normalized),
        "num_parlays": num_parlays,
        "stake_per_parlay": stake,
        "total_risk": round(stake * num_parlays, 2),
        "max_win": round(sum(profits), 2),
        "min_win": round(min_win, 2),
        "all_combinations": combinations,
        "source": "sports_derivatives",
    }
