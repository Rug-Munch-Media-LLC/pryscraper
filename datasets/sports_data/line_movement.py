"""Line movement tracking — watch odds drift over time and flag sharp moves.

Polls the live multi-sportsbook comparison for one event on every call and
records an in-memory snapshot (best-effort; no persistence). Movements are
computed per (book, outcome) between the earliest and latest snapshot inside
the lookback window. A ``sharp_signal`` fires when any outcome moved by at
least 10% relative to its opening price inside the window — the classic
early-big-move pattern that retail books trail and sharp money prints.

Because history lives in process memory, this module is best-effort by
design: it is aimed at high-frequency pollers (bots, x402-gated endpoints)
that call it repeatedly while an event is live, not at long-horizon
historical analysis (use a real store for that).

Contract
--------
* :func:`get_line_movement` — async, never raises, returns a ``dict``
  (``{}`` on unknown event / network failure). Polls
  ``sports_data.odds.get_event_odds``, records a snapshot, and computes
  movements within the lookback window.

Result shapes
-------------
``get_line_movement`` returns:

    {
        "event": "Boston Celtics @ Los Angeles Lakers",
        "event_id": "eid123",
        "market": "h2h",
        "movements": [
            {
                "book": "DraftKings",
                "outcome": "Boston Celtics",
                "from_odds": 1.85,
                "to_odds": 2.05,
                "at": "2026-08-16T18:05:00+00:00",
            },
        ],
        "sharp_signal": True,
    }

``outcome`` is the outcome name as published (team name for moneyline);
``at`` is the ISO-8601 timestamp of the newest snapshot. Books whose line
did not move inside the window are omitted from ``movements``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

# A relative move of >= 10% on an outcome inside the window counts as sharp.
_SHARP_MOVE_PCT = 0.10
# In-memory history caps: per-event snapshot ceiling + how long an event's
# history is retained after its last poll. Best-effort memory hygiene.
_MAX_SNAPSHOTS_PER_EVENT = 50
_PRUNE_AFTER_MINUTES = 180

# event_id -> list[snapshot]; snapshot = {"at": iso str, "line": {book: {outcome: odds}}}
_history: dict[str, list[dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):  # pragma: no cover - internal data is ours
        return datetime.now(UTC)


def _prune(event_id: str) -> None:
    """Drop old snapshots and stale events to keep memory bounded."""
    cutoff = datetime.now(UTC) - timedelta(minutes=_PRUNE_AFTER_MINUTES)
    retained = [
        snapshot
        for snapshot in _history.get(event_id, [])
        if _parse_at(snapshot.get("at")) >= cutoff
    ]
    if retained:
        _history[event_id] = retained[-_MAX_SNAPSHOTS_PER_EVENT:]
    else:
        _history.pop(event_id, None)


def _line_from_comparison(comparison: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map a get_event_odds comparison onto ``{book: {outcome: odds}}``."""
    line: dict[str, dict[str, float]] = {}
    bookmakers = comparison.get("bookmakers")
    if not isinstance(bookmakers, list):
        return line
    for book in bookmakers:
        if not isinstance(book, dict):
            continue
        title = str(book.get("title") or book.get("key") or "unknown")
        prices: dict[str, float] = {}
        markets = book.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            if str(market.get("key") or "h2h") != "h2h":
                continue
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "")
                price_value: Any = outcome.get("price")
                try:
                    price = float(price_value)
                except (TypeError, ValueError):
                    continue
                if name and price > 1.0:
                    prices[name] = price
        if prices:
            line[title] = prices
    return line


async def _load_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch the multi-sportsbook comparison (never raises)."""
    if _get_event_odds is None:
        return {}
    try:
        return await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_line_movement_odds_failed", extra={"event_id": event_id})
        return {}


def _compute_movements(event_id: str, lookback_minutes: int) -> tuple[list[dict[str, Any]], bool]:
    """Compute per-(book, outcome) movements inside the lookback window.

    Returns ``(movements, sharp_signal)``. ``from_odds`` is the opening
    price inside the window (earliest snapshot), ``to_odds`` the latest;
    only books/outcomes that actually moved are reported.
    """
    try:
        window = max(1, int(lookback_minutes))
    except (TypeError, ValueError):
        window = 60
    cutoff = datetime.now(UTC) - timedelta(minutes=window)
    snapshots = [
        snapshot
        for snapshot in _history.get(event_id, [])
        if _parse_at(snapshot.get("at")) >= cutoff
    ]
    movements: list[dict[str, Any]] = []
    sharp = False
    books: set[str] = set()
    outcomes: set[str] = set()
    for snapshot in snapshots:
        line = snapshot.get("line")
        if not isinstance(line, dict):
            continue
        books.update(str(book) for book in line)
        for book_prices in line.values():
            if isinstance(book_prices, dict):
                outcomes.update(str(outcome) for outcome in book_prices)
    for book in sorted(books):
        for outcome in sorted(outcomes):
            first: float | None = None
            last: float | None = None
            at = ""
            for snapshot in snapshots:
                line = snapshot.get("line")
                if not isinstance(line, dict):
                    continue
                prices = line.get(book)
                if not isinstance(prices, dict):
                    continue
                if outcome not in prices:
                    continue
                value = float(prices[outcome])
                if first is None:
                    first = value
                last = value
                at = str(snapshot.get("at") or at)
            if first is None or last is None or first == last:
                continue
            delta_pct = abs(last - first) / first * 100.0
            movements.append(
                {
                    "book": book,
                    "outcome": outcome,
                    "from_odds": round(first, 4),
                    "to_odds": round(last, 4),
                    "at": at,
                }
            )
            if delta_pct >= _SHARP_MOVE_PCT * 100.0:
                sharp = True
    movements.sort(key=lambda item: str(item.get("at") or ""))
    return movements, sharp


async def get_line_movement(event_id: str, lookback_minutes: int = 60) -> dict[str, Any]:
    """Poll live odds and report line movement for one event.

    Args:
        event_id: Event id (optionally ``sport:id`` prefixed, as accepted
            by :func:`sports_data.odds.get_event_odds`).
        lookback_minutes: Window (minutes) used to compute movements from
            the recorded in-memory history.

    Returns:
        A movement dict (see module docstring) or ``{}`` when the event is
        unknown or odds cannot be fetched. Never raises.
    """
    if not event_id or not str(event_id).strip():
        return {}
    comparison = await _load_event_odds(event_id)
    if not comparison:
        return {}
    line = _line_from_comparison(comparison)
    if not line:
        return {}
    _history.setdefault(event_id, []).append({"at": _now_iso(), "line": line})
    _prune(event_id)
    movements, sharp = _compute_movements(event_id, lookback_minutes)
    return {
        "event": str(comparison.get("event") or event_id),
        "event_id": str(comparison.get("event_id") or event_id),
        "market": "h2h",
        "movements": movements,
        "sharp_signal": sharp,
    }
