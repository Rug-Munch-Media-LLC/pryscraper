"""Steam move detection — sudden line shifts across multiple books.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from datasets.sports_data.sharp_common import (
    event_label,
    history,
    load_slate,
    now_iso,
    parse_at,
    record_snapshot,
    to_float,
)

# Minimum books that must move the same side inside the window.
STEAM_MIN_BOOKS = 3
# Books required for "high" confidence.
STEAM_HIGH_CONFIDENCE_BOOKS = 5
# Minimum absolute line change (decimal-odds points) to count as a move.
STEAM_MIN_MOVE = 0.01


def compute_steam(sport: str, lookback_minutes: int) -> list[dict[str, Any]]:
    """Detect steam moves from the recorded snapshot history."""
    try:
        window = max(1, int(lookback_minutes))
    except (TypeError, ValueError):
        window = 60
    cutoff = datetime.now(UTC) - timedelta(minutes=window)
    snapshots = [
        snapshot for snapshot in history.get(sport, []) if parse_at(snapshot.get("at")) >= cutoff
    ]
    if len(snapshots) < 2:
        return []
    first, last = snapshots[0], snapshots[-1]
    first_events = first.get("events") or {}
    last_events = last.get("events") or {}
    moves: list[dict[str, Any]] = []
    for event_id, last_books in last_events.items():
        first_books = first_events.get(event_id)
        if not isinstance(first_books, dict):
            continue
        # Collect per-outcome movement across books.
        outcomes: set[str] = set()
        for prices in last_books.values():
            if isinstance(prices, dict):
                outcomes.update(prices)
        for outcome in sorted(outcomes):
            books_moved: list[str] = []
            directions: list[float] = []
            for book_key, last_prices in last_books.items():
                first_prices = first_books.get(book_key)
                if not isinstance(first_prices, dict):
                    continue
                old = to_float(first_prices.get(outcome))
                new = to_float(last_prices.get(outcome))
                if old is None or new is None or old == new:
                    continue
                if abs(new - old) < STEAM_MIN_MOVE:
                    continue
                books_moved.append(book_key)
                directions.append(new - old)
            if len(books_moved) < STEAM_MIN_BOOKS:
                continue
            # All moved books must agree on direction for steam.
            if any((d > 0) != (directions[0] > 0) for d in directions):
                continue
            magnitude = round(max(abs(d) for d in directions), 4)
            avg_old = sum(to_float(first_books[b].get(outcome)) or 0.0 for b in books_moved) / len(
                books_moved
            )
            avg_new = sum(to_float(last_books[b].get(outcome)) or 0.0 for b in books_moved) / len(
                books_moved
            )
            confidence = "high" if len(books_moved) >= STEAM_HIGH_CONFIDENCE_BOOKS else "medium"
            moves.append(
                {
                    "event_id": event_id,
                    "event": event_label(last_events.get(event_id, {})),
                    "market": "h2h",
                    "outcome": outcome,
                    "old_line": round(avg_old, 4),
                    "new_line": round(avg_new, 4),
                    "books_moved": sorted(books_moved),
                    "move_direction": "up" if directions[0] > 0 else "down",
                    "move_magnitude": magnitude,
                    "timestamp": str(last.get("at") or ""),
                    "confidence": confidence,
                }
            )
    moves.sort(key=lambda item: -float(item.get("move_magnitude") or 0.0))
    return moves


async def get_steam_moves(sport: str = "nba", lookback_minutes: int = 60) -> list[dict[str, Any]]:
    """Detect steam moves: 1+ point shifts across 3+ books in a short window.

    Args:
        sport: Sport slug (nba, nfl, mlb, nhl, ...).
        lookback_minutes: Window for comparing the earliest vs latest
            recorded snapshot (in-memory history; poll repeatedly for
            meaningful windows).

    Returns:
        List of steam-move dicts or ``[]`` on failure. ``confidence`` is
        ``high`` when 5+ books moved simultaneously, ``medium`` otherwise.
        Never raises.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await load_slate(normalized)
    if not events:
        return []
    record_snapshot(normalized, events)
    return compute_steam(normalized, lookback_minutes)


__all__ = ["compute_steam", "get_steam_moves", "now_iso"]
