"""Bet % vs money % divergence — tickets count bets, money counts dollars.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.sharp_common import (
    event_label,
    load_bet_percentages,
    load_slate,
)

# Minimum |money_pct - bet_pct| (percentage points) to flag divergence.
DIVERGENCE_MIN = 10.0


async def get_bet_vs_money_divergence(sport: str = "nba") -> list[dict[str, Any]]:
    """Find events where bet % and money % diverge significantly.

    The sharp side is the one with more money but fewer tickets.

    Returns:
        List of divergence dicts or ``[]`` (requires ``PRY_SHARP_BET_FEED``).
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await load_slate(normalized)
    if not events:
        return []
    bet_pcts = await load_bet_percentages(normalized)
    if not bet_pcts:
        return []
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        label = event_label(event)
        pcts = bet_pcts.get(label.lower())
        if not pcts:
            continue
        for side, bet_key, money_key in (
            ("home", "home_bet", "home_money"),
            ("away", "away_bet", "away_money"),
        ):
            bet_pct = pcts.get(bet_key)
            money_pct = pcts.get(money_key)
            if bet_pct is None or money_pct is None:
                continue
            divergence = round(money_pct - bet_pct, 1)
            if abs(divergence) < DIVERGENCE_MIN:
                continue
            # Sharp side: more money, fewer bets.
            sharp_side = side if divergence > 0 else None
            confidence = (
                "high" if abs(divergence) >= 25 else ("medium" if abs(divergence) >= 15 else "low")
            )
            results.append(
                {
                    "event": label,
                    "event_id": str(event.get("id") or ""),
                    "sport": normalized,
                    "side": side,
                    "bet_pct": round(bet_pct, 1),
                    "money_pct": round(money_pct, 1),
                    "divergence": divergence,
                    "sharp_side": sharp_side,
                    "confidence": confidence,
                }
            )
    results.sort(key=lambda item: -abs(float(item.get("divergence") or 0)))
    return results


__all__ = ["get_bet_vs_money_divergence"]
