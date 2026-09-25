"""Bounded same-game parlay pool scanning."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import math
from typing import Any

from datasets.sports_data.parlay_legs.select import _combo_book, _different_class
from datasets.sports_data.parlay_math import _correlated

_MAX_POOL_LEGS = 40
_MAX_COMBOS = 600


def _scan_pool(
    pool: list[dict[str, Any]],
    *,
    event_id: str,
    event: str,
    sport: str,
    threshold: float,
) -> list[dict[str, Any]]:
    """Enumerate bounded 2-leg cross-class combos over the best-leg pool."""
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError, OverflowError):
        return []
    if not math.isfinite(threshold_value):
        return []
    capped = pool[:_MAX_POOL_LEGS]
    if len(capped) < 2:
        return []
    edges: list[dict[str, Any]] = []
    counted = 0
    for i in range(len(capped)):
        for j in range(i + 1, len(capped)):
            counted += 1
            if counted > _MAX_COMBOS:
                return edges
            a, b = capped[i], capped[j]
            if not _different_class(a, b):
                continue
            if a.get("fair_prob") is None or b.get("fair_prob") is None:
                continue
            try:
                odds_a = float(a["odds"])
                odds_b = float(b["odds"])
                implied_a = float(a["implied_prob"])
                implied_b = float(b["implied_prob"])
                fair_a = float(a["fair_prob"])
                fair_b = float(b["fair_prob"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not all(
                math.isfinite(value)
                for value in (odds_a, odds_b, implied_a, implied_b, fair_a, fair_b)
            ):
                continue
            if odds_a <= 1.0 or odds_b <= 1.0:
                continue
            combined_odds = odds_a * odds_b
            implied = implied_a * implied_b
            fair = fair_a * fair_b
            ev_pct = (fair * combined_odds - 1.0) * 100.0
            if not all(math.isfinite(value) for value in (combined_odds, implied, fair, ev_pct)):
                continue
            if ev_pct < threshold_value:
                continue
            legs_out = [
                {
                    key: leg.get(key)
                    for key in ("market", "side", "player", "team", "line", "odds", "label")
                }
                for leg in (a, b)
            ]
            edges.append(
                {
                    "event_id": event_id,
                    "event": event,
                    "sport": sport,
                    "book": _combo_book(a, b),
                    "legs": legs_out,
                    "combined_odds": round(combined_odds, 4),
                    "implied_prob": round(implied, 6),
                    "fair_prob": round(fair, 6),
                    "ev_pct": round(ev_pct, 2),
                    "correlation_flag": _correlated([a, b]),
                    "source": "sgp_scan",
                }
            )
    edges.sort(key=lambda item: float(item.get("ev_pct") or 0.0), reverse=True)
    return edges
