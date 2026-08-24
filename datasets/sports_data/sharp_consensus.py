"""Vig-free composite "sharp" consensus line — the Unabated Line equivalent.

OddsJam sells a "Unabated Line" product that composites the sharpest books'
moneylines after removing each book's margin. This module approximates it:
filter one event's multi-sportsbook comparison down to the books the market
respects most (Pinnacle, BetCRIS, Circa by default), convert each book's
two-way moneyline to a no-vig probability (``p = 1/odds`` normalized), then
average the probabilities of the books that agree into one composite line.

Contract
--------
* :func:`get_sharp_consensus` — async, never raises, returns a ``dict``
  (``{}`` on unknown event / network failure / no sharp book present).

Result shapes
-------------
``get_sharp_consensus`` returns:

    {
        "event_id": "eid123",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "market": "h2h",
        "fair_line": {"home": 2.02, "away": 1.98},
        "no_vig_prob": {"home": 0.495, "away": 0.505},
        "consensus_books": ["betcris", "circa", "pinnacle"],
        "confidence": 0.74,
        "books_used": ["betcris", "circa", "pinnacle"],
    }

``fair_line`` is the vig-free decimal moneyline implied by the consensus
probabilities; ``no_vig_prob`` the consensus probabilities themselves.
``consensus_books`` are the sharp books whose no-vig probability agrees with
the mean within :data:`_PROB_TOLERANCE` (3 percentage points); if none agree
the closest book is used alone. ``confidence`` is a 0..1 heuristic: 0.35 for
a single book, +0.20 per additional agreeing book, minus a penalty for
dispersion among the agreeing books. Home/away assignment comes from the
``"Away @ Home"`` event label published by ``sports_data.odds``, falling
back to The Odds API's conventional h2h outcome order (away first).

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

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

# Default sharp books (the Unabated-style composite) — The Odds API keys.
_SHARP_BOOKS: tuple[str, ...] = ("pinnacle", "betcris", "circa")
# Probability agreement tolerance for "consensus" membership (3 pp).
_PROB_TOLERANCE = 0.03


def _no_vig(home_odds: Any, away_odds: Any) -> tuple[float, float] | None:
    """Remove the bookmaker margin from a two-way moneyline.

    Returns ``(home_prob, away_prob)`` normalized to sum 1, or ``None`` when
    either price is unusable (non-numeric or <= 1.0).
    """
    try:
        home = float(home_odds)
        away = float(away_odds)
    except (TypeError, ValueError):
        return None
    if home <= 1.0 or away <= 1.0:
        return None
    p_home = 1.0 / home
    p_away = 1.0 / away
    total = p_home + p_away
    if total <= 0:
        return None
    return (p_home / total, p_away / total)


def _teams_from_label(event_label: str) -> tuple[str | None, str | None]:
    """Extract ``(home, away)`` from the ``"Away @ Home"`` event label."""
    raw = str(event_label or "")
    if " @ " not in raw:
        return None, None
    away, _, home = raw.partition(" @ ")
    return (home.strip() or None), (away.strip() or None)


def _comparison_h2h(
    comparison: dict[str, Any],
) -> tuple[dict[str, dict[str, float]], str, str]:
    """Map a comparison onto ``{book_key: {"home": odds, "away": odds}}``.

    Also returns the event label and event id for the caller. Outcomes are
    matched to home/away by team name (from the event label), with a
    positional fallback to The Odds API's conventional h2h order.
    """
    home_team, away_team = _teams_from_label(str(comparison.get("event") or ""))
    lines: dict[str, dict[str, float]] = {}
    bookmakers = comparison.get("bookmakers")
    if not isinstance(bookmakers, list):
        return lines, str(comparison.get("event") or ""), str(comparison.get("event_id") or "")
    for book in bookmakers:
        if not isinstance(book, dict):
            continue
        book_key = str(book.get("key") or book.get("title") or "").strip().lower()
        if not book_key:
            continue
        prices: dict[str, float] = {}
        markets = book.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            if str(mkt.get("key") or "h2h") != "h2h":
                continue
            by_name: dict[str, float] = {}
            outcomes = mkt.get("outcomes")
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
                    by_name[name] = price
            home = by_name.get(home_team) if home_team else None
            away = by_name.get(away_team) if away_team else None
            if (home is None or away is None) and len(by_name) >= 2:
                names = list(by_name)
                if home is None:
                    home = by_name.get(names[1])
                if away is None:
                    away = by_name.get(names[0])
            if home is not None and away is not None:
                prices = {"home": home, "away": away}
                break
        if prices:
            lines[book_key] = prices
    return lines, str(comparison.get("event") or ""), str(comparison.get("event_id") or "")


async def _load_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch the live multi-sportsbook comparison (never raises)."""
    if _get_event_odds is None:
        return {}
    try:
        return await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_sharp_consensus_odds_failed", extra={"event_id": event_id})
        return {}


async def get_sharp_consensus(
    event_id: str,
    books: tuple[str, ...] = _SHARP_BOOKS,
) -> dict[str, Any]:
    """Compute the vig-free composite sharp line for one event (never raises).

    Args:
        event_id: Event id to analyze.
        books: Book keys (The Odds API keys, case-insensitive) treated as
            sharp. Defaults to ``("pinnacle", "betcris", "circa")``.

    Returns:
        The consensus dict (see module docstring) or ``{}`` when the event
        is unknown, no requested sharp book prices the event, or the odds
        feed fails.
    """
    target_id = str(event_id or "").strip()
    if not target_id:
        return {}
    wanted = {str(book).strip().lower() for book in (books or ()) if str(book).strip()}
    if not wanted:
        return {}
    comparison = await _load_event_odds(target_id)
    if not comparison:
        return {}
    lines, event_label, resolved_id = _comparison_h2h(comparison)
    probs: list[tuple[str, float, float]] = []
    for book_key, prices in lines.items():
        if book_key not in wanted:
            continue
        fair = _no_vig(prices.get("home"), prices.get("away"))
        if fair is None:
            continue
        probs.append((book_key, fair[0], fair[1]))
    if not probs:
        return {}
    mean_home = sum(prob[1] for prob in probs) / len(probs)
    consensus = [
        (book_key, home_prob, away_prob)
        for book_key, home_prob, away_prob in probs
        if abs(home_prob - mean_home) <= _PROB_TOLERANCE
    ]
    if not consensus:
        consensus = [min(probs, key=lambda prob: abs(prob[1] - mean_home))]
    final_home = sum(prob[1] for prob in consensus) / len(consensus)
    # Guard against degenerate probabilities leaking into division.
    final_home = min(max(final_home, 0.02), 0.98)
    final_away = 1.0 - final_home
    max_dev = max(abs(prob[1] - mean_home) for prob in consensus)
    confidence = round(min(1.0, max(0.0, 0.35 + 0.2 * (len(consensus) - 1) - max_dev * 3.0)), 2)
    return {
        "event_id": resolved_id or target_id,
        "event": event_label,
        "market": "h2h",
        "fair_line": {
            "home": round(1.0 / final_home, 4),
            "away": round(1.0 / final_away, 4),
        },
        "no_vig_prob": {
            "home": round(final_home, 6),
            "away": round(final_away, 6),
        },
        "consensus_books": sorted(book_key for book_key, _, _ in consensus),
        "confidence": confidence,
        "books_used": sorted(book_key for book_key, _, _ in probs),
    }
