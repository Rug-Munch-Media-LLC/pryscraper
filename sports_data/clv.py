"""Closing Line Value (CLV) analytics — how much your line beat the close.

CLV is the sharpest single number a sports bettor can track: if you routinely
get better prices than the closing line, the market is telling you that you
are betting on the right side. This module computes it two ways:

* :func:`compute_clv` — pure, synchronous math for one bet: the percentage by
  which your price beat the closing price, plus the implied-probability
  "edge" you captured by taking it.
* :func:`track_clv` — async, event-level scan that compares the *current*
  multi-book line (what you could bet right now) against the *closing* line
  from :mod:`sports_data.historical` per bookmaker, so you can see which
  books are drifting your way (or away).

Definitions
-----------
``clv_pct`` = ``(bet_odds / closing_odds - 1) * 100`` — positive when the
bet price is higher (better) than the closing price. ``edge_pct`` is the same
beat expressed in implied-probability terms::

    edge_pct = (1 / closing_odds - 1 / bet_odds) * 100

Both are positive when you beat the close. Decimal odds (``> 1.0``) are
required; anything else degrades to an all-``None`` result.

Contract
--------
* :func:`compute_clv` — pure, synchronous, never raises.
* :func:`track_clv` — async, never raises, returns a ``list`` (``[]`` on
  unknown event, missing closing history, or network failure). Reuses the
  guarded-import pattern from :mod:`sports_data.line_movement` /
  :mod:`sports_data.historical` because :mod:`sports_data.odds` is owned by a
  parallel build agent.

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
from typing import Any

logger = logging.getLogger(__name__)

# Guarded imports: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported; historical is stable but kept
# guarded for symmetry (it also depends on odds).
try:
    from sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

try:
    from sports_data.historical import get_closing_line as _get_closing_line
except ImportError:  # pragma: no cover - parallel build guard
    _get_closing_line = None  # type: ignore[assignment]


def _as_odds(value: Any) -> float | None:
    """Coerce to a valid decimal price (> 1.0) or None."""
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return odds


def compute_clv(bet_odds: Any, closing_odds: Any) -> dict[str, Any]:
    """Compute the closing-line value captured by one bet.

    Args:
        bet_odds: Decimal odds you took (numeric, or garbage -> all-``None``).
        closing_odds: Decimal closing odds for the same side (same rules).

    Returns:
        ``{clv_pct, bet_odds, closing_odds, edge_pct}``. ``clv_pct`` is the
        percent by which your price beat the close; ``edge_pct`` is the same
        edge in implied-probability percentage points. Positive = you beat
        the close. Never raises.
    """
    bet = _as_odds(bet_odds)
    closing = _as_odds(closing_odds)
    if bet is None or closing is None:
        return {
            "clv_pct": None,
            "bet_odds": None,
            "closing_odds": None,
            "edge_pct": None,
        }
    clv_pct = (bet / closing - 1.0) * 100.0
    edge_pct = (1.0 / closing - 1.0 / bet) * 100.0
    return {
        "clv_pct": round(clv_pct, 4),
        "bet_odds": round(bet, 4),
        "closing_odds": round(closing, 4),
        "edge_pct": round(edge_pct, 4),
    }


def _home_away(event_label: str) -> tuple[str | None, str | None]:
    """Parse ``"Home @ Away"`` / ``"Home vs Away"`` labels into sides."""
    label = str(event_label or "").strip()
    if not label:
        return None, None
    for sep in (" @ ", " vs ", " VS ", " at "):
        if sep in label:
            parts = [part.strip() for part in label.split(sep, 1)]
            if len(parts) == 2 and all(parts):
                return parts[0], parts[1]
    return None, None


def _current_line(comparison: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map a get_event_odds comparison onto ``{book: {outcome: price}}``.

    Mirrors ``sports_data.line_movement._line_from_comparison`` but stays
    local to this module (h2h outcomes only, books keyed by display title).
    """
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
                price = _as_odds(outcome.get("price"))
                if name and price is not None:
                    prices[name] = price
        if prices:
            line[title] = prices
    return line


def _side_prices(
    prices: dict[str, float], home: str | None, away: str | None
) -> tuple[float | None, float | None]:
    """Resolve outcome-name prices onto ``(home, away)`` sides."""
    home_price = prices.get(home) if home else None
    away_price = prices.get(away) if away else None
    if (home_price is None or away_price is None) and len(prices) >= 2:
        # The Odds API h2h outcomes are conventionally ordered [away, home].
        names = list(prices)
        if home_price is None and home:
            home_price = prices.get(names[1])
        if away_price is None and away:
            away_price = prices.get(names[0])
    return home_price, away_price


async def track_clv(event_id: str) -> list[dict[str, Any]]:
    """Compare the current multi-book line against the closing line.

    Pulls the live multi-sportsbook comparison for ``event_id`` (the current
    "bet-now" line) and the closing line from
    :func:`sports_data.historical.get_closing_line`, then emits one CLV record
    per (book, side) where both a current price and a closing price exist.

    Returns:
        List of records::

            {
                "event_id": "eid123",
                "event": "Boston Celtics @ Los Angeles Lakers",
                "market": "h2h",
                "book": "DraftKings",
                "side": "home",
                "outcome": "Boston Celtics",
                "bet_odds": 2.05,        # current line (what you'd bet now)
                "closing_odds": 2.00,    # closing line for the same side
                "clv_pct": 2.5,          # positive = current line beats close
                "edge_pct": 1.22,
            }

        ``[]`` on unknown event, missing closing history, or network failure.
        Never raises.
    """
    target_id = str(event_id or "").strip()
    if not target_id:
        return []
    try:
        if _get_event_odds is None:
            return []
        comparison = await _get_event_odds(target_id)
        if not comparison:
            return []
        current = _current_line(comparison)
        if not current:
            return []
        if _get_closing_line is None:
            return []
        closing_line = await _get_closing_line(target_id)
        closing = closing_line.get("closing") if isinstance(closing_line, dict) else None
        if not isinstance(closing, dict) or not closing:
            return []
        event_label = str(comparison.get("event") or target_id)
        home, away = _home_away(event_label)
        records: list[dict[str, Any]] = []
        for book in sorted(current):
            prices = current[book]
            if not isinstance(prices, dict):
                continue
            close_odds = closing.get(book)
            if not isinstance(close_odds, dict):
                continue
            home_price, away_price = _side_prices(prices, home, away)
            for side, current_price, close_price, outcome in (
                ("home", home_price, close_odds.get("home"), home),
                ("away", away_price, close_odds.get("away"), away),
            ):
                bet = _as_odds(current_price)
                closing_price = _as_odds(close_price)
                if bet is None or closing_price is None:
                    continue
                clv = compute_clv(bet, closing_price)
                if clv.get("clv_pct") is None:
                    continue
                records.append(
                    {
                        "event_id": str(comparison.get("event_id") or target_id),
                        "event": event_label,
                        "market": "h2h",
                        "book": book,
                        "side": side,
                        "outcome": outcome or side,
                        "bet_odds": clv["bet_odds"],
                        "closing_odds": clv["closing_odds"],
                        "clv_pct": clv["clv_pct"],
                        "edge_pct": clv["edge_pct"],
                    }
                )
        return records
    except Exception:
        logger.exception("sports_clv_track_failed", extra={"event_id": target_id})
        return []
