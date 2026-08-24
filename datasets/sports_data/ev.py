"""Positive expected-value (EV) detection using a sharp book as the anchor.

The idea behind "more than OddsJam": instead of merely listing who has the
best price, we estimate the *fair* probability of each outcome from the
sharpest book's moneyline (the market consensus, least juiced), then flag
any book whose price implies a better payout than the fair probability
justifies. A bet is +EV when ``fair_prob * decimal_odds - 1 > 0``.

The no-vig fair probability is computed from a two-way line::

    p_home = (1/home) / (1/home + 1/away)

which removes the bookmaker's margin from the sharp book's quote. Pinnacle
is the conventional sharp book; any bookmaker name can be passed instead.

Contract
--------
* :func:`find_plus_ev` — async, never raises, returns a ``list`` (``[]``
  on failure / no edges). Scans ``sports_data.odds.get_odds``, anchors on
  the sharp book's line per (event, market), and keeps bets whose EV clears
  ``min_ev_pct``.
* :func:`compute_no_vig` — pure, synchronous, unit-testable helper.

Result shapes
-------------
``find_plus_ev`` returns a list of:

    {
        "event": "Boston Celtics @ Los Angeles Lakers",
        "event_id": "eid123",
        "sport": "nba",
        "market": "h2h",
        "side": "away",
        "book": "FanDuel",
        "odds": 2.20,
        "fair_prob": 0.5,
        "implied_prob": 0.4545,
        "ev_pct": 10.0,
    }

``compute_no_vig`` returns:

    {
        "home_prob": 0.5,
        "away_prob": 0.5,
        "margin": 0.0,          # bookmaker overround (0 = fair)
        "fair_home_odds": 2.0,
        "fair_away_odds": 2.0,
    }

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
    from datasets.sports_data.odds import get_odds as _get_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_odds = None  # type: ignore[assignment]

_DEFAULT_MIN_EV = 2.0
_DEFAULT_SHARP = "pinnacle"


def compute_no_vig(home_odds: Any, away_odds: Any) -> dict[str, Any]:
    """Compute the no-vig "fair" probabilities from a two-way moneyline.

    Args:
        home_odds: Decimal odds for the home side (numeric, or garbage ->
            ``None`` result).
        away_odds: Decimal odds for the away side (same).

    Returns:
        Fair probabilities (normalized to sum 1), the bookmaker margin, and
        the fair decimal odds implied by those probabilities. Never raises;
        unusable input degrades to an all-``None`` dict.
    """
    try:
        home = float(home_odds)
        away = float(away_odds)
    except (TypeError, ValueError):
        return {
            "home_prob": None,
            "away_prob": None,
            "margin": None,
            "fair_home_odds": None,
            "fair_away_odds": None,
        }
    if home <= 1.0 or away <= 1.0:
        return {
            "home_prob": None,
            "away_prob": None,
            "margin": None,
            "fair_home_odds": None,
            "fair_away_odds": None,
        }
    p_home = 1.0 / home
    p_away = 1.0 / away
    implied = p_home + p_away
    margin = implied - 1.0
    fair_home = p_home / implied
    fair_away = p_away / implied
    return {
        "home_prob": round(fair_home, 6),
        "away_prob": round(fair_away, 6),
        "margin": round(margin, 6),
        "fair_home_odds": round(1.0 / fair_home, 4),
        "fair_away_odds": round(1.0 / fair_away, 4),
    }


async def _load_odds() -> list[dict[str, Any]]:
    """Fetch live odds records (never raises)."""
    if _get_odds is None:
        return []
    try:
        return await _get_odds(sport="all", limit=100)
    except Exception:
        logger.exception("sports_ev_odds_failed")
        return []


def _group_records(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    """Group canonical odds records into per-(sport, event, market) buckets."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (
            str(record.get("sport") or ""),
            str(record.get("event") or ""),
            str(record.get("event_id") or ""),
            str(record.get("market") or "h2h"),
        )
        groups.setdefault(key, []).append(record)
    return groups


def _record_odds(record: dict[str, Any], side: str) -> float | None:
    """Extract decimal odds for ``home``/``away`` from a canonical record."""
    value: Any = record.get(f"{side}_odds")
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return odds


async def find_plus_ev(
    sharp_book: str = _DEFAULT_SHARP, min_ev_pct: float = _DEFAULT_MIN_EV
) -> list[dict[str, Any]]:
    """Scan live odds for +EV bets against the sharp book's fair line.

    Args:
        sharp_book: Bookmaker used as the no-vig anchor (default
            ``"pinnacle"``, matched case-insensitively).
        min_ev_pct: Only keep bets with at least this EV (percent).

    Returns:
        List of +EV records (see module docstring), best EV first. ``[]``
        on failure, when no sharp line exists for an event, or when nothing
        clears the threshold. Never raises.
    """
    try:
        threshold = max(0.0, float(min_ev_pct))
    except (TypeError, ValueError):
        threshold = _DEFAULT_MIN_EV
    anchor = (sharp_book or _DEFAULT_SHARP).strip().lower()
    records = await _load_odds()
    edges: list[dict[str, Any]] = []
    for key, group in _group_records(records).items():
        sport_name, event, event_id, market = key
        sharp_records = [
            record for record in group if str(record.get("bookmaker") or "").lower() == anchor
        ]
        if not sharp_records:
            continue
        sharp = sharp_records[0]
        sharp_home = _record_odds(sharp, "home")
        sharp_away = _record_odds(sharp, "away")
        if sharp_home is None or sharp_away is None:
            continue
        fair = compute_no_vig(sharp_home, sharp_away)
        if fair.get("home_prob") is None:
            continue
        fair_home = float(fair["home_prob"])
        fair_away = float(fair["away_prob"])
        for record in group:
            book = str(record.get("bookmaker") or "unknown")
            if book.lower() == anchor:
                continue  # never flag the anchor itself
            for side, fair_prob in (("home", fair_home), ("away", fair_away)):
                odds = _record_odds(record, side)
                if odds is None:
                    continue
                implied = 1.0 / odds
                ev = fair_prob * odds - 1.0
                ev_pct = ev * 100.0
                if ev_pct >= threshold:
                    edges.append(
                        {
                            "event": event,
                            "event_id": event_id,
                            "sport": sport_name,
                            "market": market,
                            "side": side,
                            "book": book,
                            "odds": odds,
                            "fair_prob": round(fair_prob, 6),
                            "implied_prob": round(implied, 6),
                            "ev_pct": round(ev_pct, 2),
                        }
                    )
    edges.sort(key=lambda item: float(item.get("ev_pct") or 0.0), reverse=True)
    return edges
