"""If-bet scenario and pricing math."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import itertools
import logging
from typing import Any

from .legs import _normalize_legs
from .odds_math import decimal_to_american, effective_decimal

logger = logging.getLogger(__name__)


def _if_bet_scenarios(normalized: list[dict[str, Any]], stake: float) -> list[dict[str, Any]]:
    """Enumerate win/loss scenarios for a sequential if-bet chain.

    Leg ``i+1`` is only placed (risking ``stake``) if every earlier leg won.
    Returns one record per outcome path with the legs placed and net result.
    """
    scenarios: list[dict[str, Any]] = []
    count = len(normalized)
    for bits in itertools.product((True, False), repeat=count):
        placed: list[str] = []
        net = 0.0
        for index, won in enumerate(bits):
            if not won:
                # The leg was placed (all earlier legs won) and lost its stake.
                net -= stake
                break
            leg = normalized[index]
            placed.append(str(leg["selection"]))
            net += stake * (float(leg["decimal_odds"]) - 1.0)  # win: profit, stake returns
        scenarios.append(
            {
                "outcomes": ["win" if b else "loss" for b in bits],
                "legs_placed": placed,
                "net": round(net, 2),
            }
        )
    return scenarios


def price_if_bet(legs: list[dict[str, Any]], max_risk: float = 100) -> dict[str, Any]:
    """Price an if-bet (conditional chain: leg 2 only runs if leg 1 wins).

    Args:
        legs: Ordered leg dicts; later legs are conditional on earlier wins.
        max_risk: Stake risked on each placed leg (default 100).

    Returns:
        Dict with ``scenarios``, ``max_win``, ``max_loss`` and
        ``effective_odds`` — or ``{}`` when fewer than two valid legs remain.
        Never raises.
    """
    try:
        return _price_if_bet(legs, max_risk)
    except Exception:
        logger.exception("sports_if_bet_price_crashed")
        return {}


def _price_if_bet(legs: list[dict[str, Any]], max_risk: float) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    stake = max(0.0, float(max_risk if max_risk is not None else 100))
    scenarios = _if_bet_scenarios(normalized, stake)
    nets = [float(s["net"]) for s in scenarios]
    max_win = max(nets)
    max_loss = min(nets)
    decimal = effective_decimal(max_win, stake)
    return {
        "bet_type": "if_bet",
        "leg_count": len(normalized),
        "stake_per_leg": round(stake, 2),
        "scenarios": scenarios,
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
        "effective_odds": {
            "decimal": decimal,
            "american": decimal_to_american(decimal),
        },
        "source": "sports_derivatives",
    }
