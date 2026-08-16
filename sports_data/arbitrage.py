"""Arbitrage detection across sportsbooks — the "more than OddsJam" edge.

Scans live odds from :mod:`sports_data.odds` for the same event offered at
prices across multiple books, converts decimal odds to implied probabilities
(2-way moneyline: ``p = 1/odds``; 3-way: ``p = 1/o_home + 1/o_away +
1/o_draw``) and flags any combination whose implied total is below 1.0 — the
classic guaranteed-profit arbitrage. The yield is expressed the way OddsJam
does: ``(1 - total_implied) / total_implied * 100``.

Contract
--------
* :func:`find_arbitrage` — async, never raises, returns a ``list`` (``[]``
  on failure / no opportunities). Scans ``sports_data.odds.get_odds`` for
  every (event, market) group, picks the best price per side across books,
  and keeps opportunities whose yield clears ``min_yield_pct``.
* :func:`detect_2way_arb` / :func:`detect_3way_arb` — pure, synchronous,
  unit-testable helpers. Each side is either a bare decimal ``float`` or a
  ``{"book": str, "odds": float}`` dict. Return ``None`` when the
  combination is not an arb (or input is unusable).

Result shapes
-------------
``find_arbitrage`` returns a list of:

    {
        "event": "Boston Celtics @ Los Angeles Lakers",
        "event_id": "eid123",
        "sport": "nba",
        "market": "h2h",
        "books": {
            "home": {"book": "DraftKings", "odds": 2.10},
            "away": {"book": "FanDuel", "odds": 2.10},
        },
        "total_implied": 0.9524,
        "arb_yield_pct": 5.0,
        "stake_split": {"home_pct": 50.0, "away_pct": 50.0},
    }

``stake_split`` is the proportion of the stake to place on each side so every
outcome pays the same (the no-vig allocation). 3-way entries additionally
carry a ``draw`` side under ``books`` and ``draw_pct`` under ``stake_split``.

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
    from sports_data.odds import get_odds as _get_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_odds = None  # type: ignore[assignment]

_MIN_DECIMAL_ODDS = 1.0  # decimal odds must exceed 1 (an edge), never 0/1
_SIDES_2WAY = ("home", "away")
_SIDES_3WAY = ("home", "away", "draw")


def _side_to_odds(side: Any) -> dict[str, Any] | None:
    """Normalize a side into ``{"book": str, "odds": float}`` or ``None``.

    Accepts either a bare decimal odds value or a ``{"book", "odds"}`` dict.
    Invalid odds (non-numeric, <= 1.0) yield ``None`` so callers never have
    to defensively check floats.
    """
    odds: Any
    book: Any = "unknown"
    if isinstance(side, dict):
        odds = side.get("odds")
        book = side.get("book") or "unknown"
    else:
        odds = side
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    if value <= _MIN_DECIMAL_ODDS:
        return None
    return {"book": str(book), "odds": round(value, 6)}


def _arb_result(market: str, sides: list[dict[str, Any]]) -> dict[str, Any]:
    """Compose the canonical arb record from normalized sides."""
    probabilities = [1.0 / side["odds"] for side in sides]
    total_implied = sum(probabilities)
    yield_pct = (1.0 - total_implied) / total_implied * 100.0
    split_total = sum(probabilities)
    books: dict[str, Any] = {}
    stake_split: dict[str, Any] = {}
    for key, side, prob in zip(_SIDES_3WAY, sides, probabilities, strict=False):
        books[key] = {"book": side["book"], "odds": side["odds"]}
        stake_split[f"{key}_pct"] = round(prob / split_total * 100.0, 2)
    return {
        "market": market,
        "books": books,
        "total_implied": round(total_implied, 4),
        "arb_yield_pct": round(yield_pct, 2),
        "stake_split": stake_split,
    }


def detect_2way_arb(home_book_odds: Any, away_book_odds: Any) -> dict[str, Any] | None:
    """Detect a 2-way (moneyline) arbitrage between the two best sides.

    Args:
        home_book_odds: Best available home price (``{"book", "odds"}`` or
            bare decimal odds; garbage -> ``None``).
        away_book_odds: Best available away price (same shapes).

    Returns:
        An arb record (see module docstring) when the implied total is
        below 1.0, otherwise ``None``. Never raises.
    """
    home = _side_to_odds(home_book_odds)
    away = _side_to_odds(away_book_odds)
    if home is None or away is None:
        return None
    if 1.0 / home["odds"] + 1.0 / away["odds"] >= 1.0:
        return None
    return _arb_result("h2h", [home, away])


def detect_3way_arb(
    home_book_odds: Any,
    away_book_odds: Any,
    draw_book_odds: Any,
) -> dict[str, Any] | None:
    """Detect a 3-way (home/away/draw) arbitrage across three best sides.

    Used for soccer-style moneyline markets where a draw is a real outcome.
    Same input/return contract as :func:`detect_2way_arb` plus a ``draw``
    side. Never raises.
    """
    home = _side_to_odds(home_book_odds)
    away = _side_to_odds(away_book_odds)
    draw = _side_to_odds(draw_book_odds)
    if home is None or away is None or draw is None:
        return None
    if sum(1.0 / side["odds"] for side in (home, away, draw)) >= 1.0:
        return None
    return _arb_result("h2h_3way", [home, away, draw])


async def _load_odds(sport: str) -> list[dict[str, Any]]:
    """Fetch live odds records (never raises)."""
    if _get_odds is None:
        return []
    try:
        return await _get_odds(sport=sport, limit=100)
    except Exception:
        logger.exception("sports_arbitrage_odds_failed", extra={"sport": sport})
        return []


def _group_records(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """Group canonical odds records into per-(sport, event, market) books.

    Each group maps bookmaker title -> side odds::

        {
            "DraftKings": {"home": 2.10, "away": 1.80},
            "FanDuel":    {"home": 2.00, "away": 2.10, "draw": 3.40},
        }
    """
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (
            str(record.get("sport") or ""),
            str(record.get("event") or ""),
            str(record.get("event_id") or ""),
            str(record.get("market") or "h2h"),
        )
        book = str(record.get("bookmaker") or "unknown")
        group = groups.setdefault(key, {})
        sides = group.setdefault(book, {})
        home = _side_to_odds({"book": book, "odds": record.get("home_odds")})
        away = _side_to_odds({"book": book, "odds": record.get("away_odds")})
        draw = _side_to_odds({"book": book, "odds": record.get("draw_odds")})
        if home is not None:
            sides["home"] = home
        if away is not None:
            sides["away"] = away
        if draw is not None:
            sides["draw"] = draw
    return groups


def _best_side(group: dict[str, dict[str, Any]], side: str) -> dict[str, Any] | None:
    """Return the best (highest) odds for ``side`` across the group's books."""
    best: dict[str, Any] | None = None
    for sides in group.values():
        entry = sides.get(side)
        if entry is None:
            continue
        if best is None or entry["odds"] > best["odds"]:
            best = entry
    return best


async def find_arbitrage(sport: str = "all", min_yield_pct: float = 0.5) -> list[dict[str, Any]]:
    """Scan live odds for arbitrage opportunities across books.

    Args:
        sport: Sport name (see :mod:`sports_data.odds`) or ``"all"``.
        min_yield_pct: Only keep opportunities with at least this
            guaranteed yield (percent).

    Returns:
        List of arb records (see module docstring), best yield first.
        ``[]`` on failure or when nothing clears the threshold. Never
        raises. Best-effort: 3-way detection engages when draw odds are
        present in the feed; the canonical moneyline records are 2-way, so
        in practice most opportunities are 2-way moneyline arbs.
    """
    try:
        threshold = max(0.0, float(min_yield_pct))
    except (TypeError, ValueError):
        threshold = 0.5
    records = await _load_odds(sport)
    opportunities: list[dict[str, Any]] = []
    for key, group in _group_records(records).items():
        sport_name, event, event_id, market = key
        # 2-way: best home and best away prices across books.
        best_home = _best_side(group, "home")
        best_away = _best_side(group, "away")
        if best_home is not None and best_away is not None:
            arb = detect_2way_arb(best_home, best_away)
            if arb is not None:
                arb.update(
                    {
                        "event": event,
                        "event_id": event_id,
                        "sport": sport_name,
                        "market": market or arb.get("market", "h2h"),
                    }
                )
                opportunities.append(arb)
        # 3-way: engage only when a book actually publishes a draw price.
        best_draw = _best_side(group, "draw")
        if best_home is not None and best_away is not None and best_draw is not None:
            arb3 = detect_3way_arb(best_home, best_away, best_draw)
            if arb3 is not None:
                arb3.update(
                    {
                        "event": event,
                        "event_id": event_id,
                        "sport": sport_name,
                        "market": market or "h2h_3way",
                    }
                )
                opportunities.append(arb3)
    opportunities.sort(key=lambda item: float(item.get("arb_yield_pct") or 0.0), reverse=True)
    return [item for item in opportunities if float(item.get("arb_yield_pct") or 0.0) >= threshold]
