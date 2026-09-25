"""Reverse-bet pricing math."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from .if_bets import _if_bet_scenarios
from .legs import _normalize_legs

logger = logging.getLogger(__name__)


def price_reverse_bet(legs: list[dict[str, Any]], max_risk: float = 100) -> dict[str, Any]:
    """Price a reverse bet (two if-bets: A→B and B→A).

    Args:
        legs: Leg dicts (exactly the two directions are priced).
        max_risk: Stake risked per if-bet chain (default 100).

    Returns:
        Dict with ``scenarios`` (per chain), ``max_win`` and ``max_loss``
        across both directions — or ``{}`` when fewer than two valid legs
        remain. Never raises.
    """
    try:
        return _price_reverse_bet(legs, max_risk)
    except Exception:
        logger.exception("sports_reverse_price_crashed")
        return {}


def _price_reverse_bet(legs: list[dict[str, Any]], max_risk: float) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    stake = max(0.0, float(max_risk if max_risk is not None else 100))
    chains = []
    combined_nets: list[float] = []
    for order in ((0, 1), (1, 0)):
        pair = [normalized[order[0]], normalized[order[1]]]
        chain_scenarios = _if_bet_scenarios(pair, stake)
        chain_nets = [float(s["net"]) for s in chain_scenarios]
        chains.append(
            {
                "direction": f"{pair[0]['selection']} → {pair[1]['selection']}",
                "scenarios": chain_scenarios,
                "max_win": round(max(chain_nets), 2),
                "max_loss": round(min(chain_nets), 2),
            }
        )
    # Combined result per outcome path: both chains settle on the same
    # leg outcomes, so net = chain A→B net + chain B→A net per scenario.
    if len(chains) == 2 and len(chains[0]["scenarios"]) == len(chains[1]["scenarios"]):
        combined_nets = [
            float(a["net"]) + float(b["net"])
            for a, b in zip(chains[0]["scenarios"], chains[1]["scenarios"], strict=True)
        ]
    else:  # pragma: no cover - defensive
        combined_nets = [float(s["net"]) for chain in chains for s in chain["scenarios"]]
    return {
        "bet_type": "reverse",
        "leg_count": len(normalized),
        "stake_per_chain": round(stake, 2),
        "total_risk": round(stake * 2, 2),
        "chains": chains,
        "scenarios": chains,
        "max_win": round(max(combined_nets), 2),
        "max_loss": round(min(combined_nets), 2),
        "source": "sports_derivatives",
    }
