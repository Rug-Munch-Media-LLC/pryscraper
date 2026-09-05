"""Reverse line movement (RLM) — line moved toward the less-bet side.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.sharp_common import (
    event_label,
    history,
    load_bet_percentages,
    load_slate,
    record_snapshot,
)

# Minimum line move (decimal odds ratio) for an RLM signal to fire.
RLM_MIN_MOVE_PCT = 0.02


async def get_reverse_line_movement(sport: str = "nba") -> list[dict[str, Any]]:
    """Find reverse line movement: line moved toward the less-bet side.

    Args:
        sport: Sport slug (nba, nfl, mlb, nhl, ...).

    Returns:
        List of RLM dicts or ``[]`` on failure. Requires the
        ``PRY_SHARP_BET_FEED`` betting-percentage feed; without it, public
        percentages are unknown and no RLM signal is fabricated.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await load_slate(normalized)
    if not events:
        return []
    record_snapshot(normalized, events)
    bet_pcts = await load_bet_percentages(normalized)
    if not bet_pcts:
        return []
    snapshots = history.get(normalized) or []
    if len(snapshots) < 2:
        return []
    first_events = snapshots[0].get("events") or {}
    last_events = snapshots[-1].get("events") or {}
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        label = event_label(event)
        pcts = bet_pcts.get(label.lower())
        if not pcts or not event_id:
            continue
        first_books = first_events.get(event_id)
        last_books = last_events.get(event_id)
        if not isinstance(first_books, dict) or not isinstance(last_books, dict):
            continue
        for side, bet_key, _money_key in (
            ("home", "home_bet", "home_money"),
            ("away", "away_bet", "away_money"),
        ):
            bet_pct = pcts.get(bet_key)
            if bet_pct is None:
                continue
            # Movement proxy: average h2h price change across books present
            # in both snapshots.
            deltas: list[float] = []
            first_price = 0.0
            for book_key, last_prices in last_books.items():
                first_prices = first_books.get(book_key)
                if not isinstance(first_prices, dict):
                    continue
                # h2h outcomes are keyed "Team|h2h"; match by team prefix.
                team = str(event.get("home_team") if side == "home" else event.get("away_team"))
                matches_last = [v for k, v in last_prices.items() if k.startswith(f"{team}|h2h")]
                matches_first = [v for k, v in first_prices.items() if k.startswith(f"{team}|h2h")]
                if not matches_last or not matches_first:
                    continue
                delta = matches_last[0] - matches_first[0]
                if abs(delta) >= RLM_MIN_MOVE_PCT * matches_first[0]:
                    deltas.append(delta)
                    first_price = matches_first[0]
            if not deltas:
                continue
            moved = sum(deltas) / len(deltas)
            # RLM: line moved toward the side with LESS public betting.
            # Odds moving down (shorter) = market backing that side.
            less_bet_side = bet_pct < 50.0
            moved_toward = moved < 0 if less_bet_side else moved > 0
            rlm_signal = moved_toward and bet_pct <= 40.0
            divergence = abs(50.0 - bet_pct)
            strength = (
                "strong"
                if divergence >= 25 and rlm_signal
                else ("moderate" if rlm_signal else "weak")
            )
            results.append(
                {
                    "event": label,
                    "event_id": event_id,
                    "sport": normalized,
                    "side": side,
                    "public_bet_pct": round(bet_pct, 1),
                    "line_movement": "toward" if moved_toward else "away",
                    "line_move_pct": round(moved / max(first_price, 1.0) * 100.0, 2),
                    "rlm_signal": rlm_signal,
                    "strength": strength,
                }
            )
    return [item for item in results if item.get("rlm_signal")]


__all__ = ["get_reverse_line_movement"]
