"""Line watch — current vs opening line, best book, value indicator.

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
    load_slate,
    record_snapshot,
    to_float,
)


async def get_line_watch(sport: str = "nba") -> list[dict[str, Any]]:
    """Lines worth watching: current vs opening, best book, value indicator.

    Returns:
        List of line-watch dicts or ``[]`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await load_slate(normalized)
    if not events:
        return []
    record_snapshot(normalized, events)
    snapshots = history.get(normalized) or []
    first_events = snapshots[0].get("events") if snapshots else {}
    last_events = snapshots[-1].get("events") if snapshots else {}
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        last_books = (last_events or {}).get(event_id)
        if not isinstance(last_books, dict) or not last_books:
            continue
        first_books = (first_events or {}).get(event_id) or {}
        # Consensus = mean price per outcome across books.
        consensus: dict[str, float] = {}
        counts: dict[str, int] = {}
        for prices in last_books.values():
            if not isinstance(prices, dict):
                continue
            for outcome, price in prices.items():
                value = to_float(price)
                if value is None:
                    continue
                consensus[outcome] = consensus.get(outcome, 0.0) + value
                counts[outcome] = counts.get(outcome, 0) + 1
        for outcome in list(consensus):
            if counts.get(outcome):
                consensus[outcome] = consensus[outcome] / counts[outcome]
        best_book: str | None = None
        best_price: float | None = None
        movement_total = 0.0
        movement_count = 0
        for book_key, prices in last_books.items():
            if not isinstance(prices, dict):
                continue
            for outcome, price in prices.items():
                value = to_float(price)
                if value is None:
                    continue
                # "Best" line for a bettor = highest decimal price on any
                # outcome (better payout than consensus).
                if best_price is None or value > best_price:
                    best_price = value
                    best_book = book_key
                first_prices = first_books.get(book_key)
                if isinstance(first_prices, dict):
                    old = to_float(first_prices.get(outcome))
                    if old is not None and old != value:
                        movement_total += value - old
                        movement_count += 1
        if best_book is None:
            continue
        avg_movement = round(movement_total / movement_count, 4) if movement_count else 0.0
        # Value indicator: best price vs consensus on the same outcome.
        outcome_of_best = next(
            (o for o, p in last_books.get(best_book, {}).items() if to_float(p) == best_price),
            None,
        )
        value_indicator = "good_line"
        if outcome_of_best and outcome_of_best in consensus:
            edge = best_price - consensus[outcome_of_best]
            value_indicator = (
                "good_line" if edge > 0.01 else ("bad_line" if edge < -0.01 else "fair_line")
            )
        results.append(
            {
                "event": event_label(event),
                "event_id": event_id,
                "sport": normalized,
                "market": "h2h",
                "current_line": round(best_price, 4) if best_price is not None else None,
                "opening_line": round(
                    (
                        to_float((first_books.get(best_book) or {}).get(outcome_of_best))
                        or best_price
                    ),
                    4,
                )
                if best_price is not None
                else None,
                "movement": avg_movement,
                "best_line": {
                    "book": best_book,
                    "price": round(best_price, 4) if best_price else None,
                },
                "value_indicator": value_indicator,
            }
        )
    return results


__all__ = ["get_line_watch"]
