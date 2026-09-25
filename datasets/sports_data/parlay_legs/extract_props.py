"""Player-prop extraction for parlay legs."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.parlay_legs.fair import _fair_probability
from datasets.sports_data.parlay_math import _as_text, _to_float


def _prop_legs_from_records(records: list[dict[str, Any]], book: str) -> list[dict[str, Any]]:
    """Build over/under legs from game-prop records for one book."""
    if not isinstance(records, list) or not isinstance(book, str):
        return []
    legs: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("book") or "").casefold() != book.casefold():
            continue
        player = _as_text(record.get("player"))
        if not player:
            continue
        market = str(record.get("market") or "").strip().lower()
        line = _to_float(record.get("line"))
        over_odds = _to_float(record.get("over_odds"))
        under_odds = _to_float(record.get("under_odds"))
        if over_odds is not None:
            fair = _fair_probability(over_odds, over_odds, under_odds)
            legs.append(
                {
                    "market": market,
                    "side": "over",
                    "player": player,
                    "team": _as_text(record.get("team")),
                    "line": line,
                    "odds": over_odds,
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / over_odds, 6),
                    "label": f"{player} Over {line}" if line is not None else f"{player} Over",
                    "book": book,
                }
            )
        if under_odds is not None:
            fair = _fair_probability(under_odds, over_odds, under_odds)
            legs.append(
                {
                    "market": market,
                    "side": "under",
                    "player": player,
                    "team": _as_text(record.get("team")),
                    "line": line,
                    "odds": under_odds,
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / under_odds, 6),
                    "label": f"{player} Under {line}" if line is not None else f"{player} Under",
                    "book": book,
                }
            )
    return legs
