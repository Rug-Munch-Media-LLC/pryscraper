"""Player prop projections — honest season-average heuristics, labeled.

Projects a player's expected line for a prop market from their current
season per-game averages (ESPN public stats via
:func:`sports_data.stats.get_player_stats`) with an optional matchup
multiplier. This is a **transparent heuristic, not a model**: every number
in the result is derived from a documented source and the ``source`` field
is always ``"projection"`` so callers can never confuse it with a real
bookmaker line (the same convention as :mod:`sports_data.props`).

What it does
------------
* **season_avg** — the parsed per-game stat for the requested market
  (e.g. ``"Points Per Game"`` for ``market="points"``).
* **last_5_avg** — the "last 5 games" stat when the ESPN payload carries one
  (keys containing ``last 5``); otherwise it honestly falls back to
  ``season_avg`` (no fabrication of a recency number we do not have).
* **matchup_factor** — a multiplier on the line. Neutral ``1.0`` by default
  because the stats feed carries no opponent/schedule context; callers with
  a matchup model can pass one explicitly (keyword-only).
* **projected_line** — ``season_avg * matchup_factor`` (sum of components for
  derived markets such as ``"pra"`` = points + rebounds + assists).
* **confidence** — an honest 0-100 heuristic from data quality (payload
  completeness, market variance), *not* a probability.

Contract
--------
* :func:`project_player_prop` — async, never raises, returns a ``dict``
  (``{}`` on unknown player, unsupported market, or network failure).

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

# Guarded import: sports_data.stats depends on sports_data.odds (parallel
# agent's file); guard so this module imports cleanly even mid-build.
try:
    from datasets.sports_data.stats import get_player_stats as _get_player_stats
except ImportError:  # pragma: no cover - parallel build guard
    _get_player_stats = None  # type: ignore[assignment]

# market slug -> candidate ESPN stat labels, in preference order (exact key
# match first, then case-insensitive substring over the payload's keys).
_MARKET_LABELS: dict[str, list[str]] = {
    "points": ["Points Per Game", "PPG"],
    "rebounds": ["Rebounds Per Game", "RPG"],
    "assists": ["Assists Per Game", "APG"],
    "steals": ["Steals Per Game", "SPG"],
    "blocks": ["Blocks Per Game", "BPG"],
    "turnovers": ["Turnovers Per Game", "TOV"],
    "threes": [
        "Three Point Field Goals Per Game",
        "Three Pointers Made Per Game",
        "Three Pointers Per Game",
        "3PM",
    ],
    "fantasy": ["Fantasy Points"],
    "double_double": ["Double-Doubles", "Double Doubles"],
    # Derived market: sum of the three components (computed when available).
    "pra": ["Points + Rebounds + Assists", "PRA"],
}

# Markets whose lines are volatile enough that a season average is a weaker
# signal (shaved from confidence).
_HIGH_VARIANCE_MARKETS = {"steals", "blocks", "turnovers"}

# Clamp for an explicitly-passed matchup multiplier.
_MATCHUP_MIN = 0.5
_MATCHUP_MAX = 1.5


def _as_float(value: Any) -> float | None:
    """Coerce a stat value to float (garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_stat(stats: dict[str, Any], labels: list[str]) -> float | None:
    """Look up the first matching stat by exact key then substring/alias."""
    if not isinstance(stats, dict):
        return None
    for label in labels:
        if label in stats:
            value = _as_float(stats[label])
            if value is not None:
                return value
    needle = labels[0].lower() if labels else ""
    for key, value in stats.items():
        haystack = str(key or "").lower()
        if needle and needle in haystack:
            parsed = _as_float(value)
            if parsed is not None:
                return parsed
    for alias in labels[1:]:
        low = alias.lower()
        for key, value in stats.items():
            if low in str(key or "").lower():
                parsed = _as_float(value)
                if parsed is not None:
                    return parsed
    return None


def _find_last_5(stats: dict[str, Any], labels: list[str]) -> float | None:
    """Look for a "last 5 games" variant of the stat (best-effort)."""
    if not isinstance(stats, dict):
        return None
    for key, value in stats.items():
        haystack = str(key or "").lower()
        if "last 5" not in haystack and "last5" not in haystack:
            continue
        if not any(label.lower() in haystack for label in labels):
            continue
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _confidence(
    *,
    season_avg: float | None,
    last_5_avg: float | None,
    position: str | None,
    team: str | None,
    market: str,
) -> int:
    """Honest data-quality score in 0-100 (not a probability)."""
    score = 50
    if season_avg is not None:
        score += 15
    if last_5_avg is not None and last_5_avg != season_avg:
        score += 10  # real recency data, not a fallback
    if team:
        score += 10
    if position:
        score += 5
    if market in _HIGH_VARIANCE_MARKETS:
        score -= 10
    return max(0, min(100, score))


async def project_player_prop(
    player: str,
    market: str,
    sport: str,
    *,
    matchup_factor: float | None = None,
) -> dict[str, Any]:
    """Project a player prop line from season averages + matchup.

    Args:
        player: Player name (or numeric ESPN athlete id), as accepted by
            :func:`sports_data.stats.get_player_stats`.
        market: Prop market slug — ``points``, ``rebounds``, ``assists``,
            ``steals``, ``blocks``, ``turnovers``, ``threes``, ``fantasy``,
            ``double_double``, or ``pra`` (derived sum).
        sport: Sport key (``nba``, ``nfl``, ...).
        matchup_factor: Optional multiplier on the line (keyword-only).
            Defaults to neutral ``1.0``; the stats feed carries no
            opponent/schedule context, so any non-neutral value must come
            from the caller's own matchup model.

    Returns:
        A projection record (see module docstring) with
        ``source: "projection"``, or ``{}`` on unknown player, unsupported
        market, or failure. Never raises.
    """
    name = str(player or "").strip()
    market_key = str(market or "").strip().lower()
    sport_key = str(sport or "").strip().lower()
    if not name or not market_key or not sport_key:
        return {}
    labels = _MARKET_LABELS.get(market_key)
    if not labels:
        return {}
    try:
        factor = float(matchup_factor) if matchup_factor is not None else 1.0
    except (TypeError, ValueError):
        factor = 1.0
    factor = max(_MATCHUP_MIN, min(_MATCHUP_MAX, factor))
    try:
        if _get_player_stats is None:
            record = {}
        else:
            record = await _get_player_stats(name, sport_key)
    except Exception:
        logger.exception(
            "sports_projection_stats_failed",
            extra={"player": name, "market": market_key, "sport": sport_key},
        )
        record = {}
    if not isinstance(record, dict) or not record:
        return {}
    stats = record.get("stats")
    if not isinstance(stats, dict) or not stats:
        return {}

    season_avg: float | None
    last_5: float | None
    if market_key == "pra":
        points = _find_stat(stats, _MARKET_LABELS["points"])
        rebounds = _find_stat(stats, _MARKET_LABELS["rebounds"])
        assists = _find_stat(stats, _MARKET_LABELS["assists"])
        if points is None or rebounds is None or assists is None:
            return {}
        season_avg = points + rebounds + assists
        last_5_parts = [
            _find_last_5(stats, labels_list)
            for labels_list in (
                _MARKET_LABELS["points"],
                _MARKET_LABELS["rebounds"],
                _MARKET_LABELS["assists"],
            )
        ]
        if all(part is not None for part in last_5_parts):
            last_5 = sum(part for part in last_5_parts if part is not None)
        else:
            last_5 = None
    else:
        season_avg = _find_stat(stats, labels)
        if season_avg is None:
            return {}
        last_5 = _find_last_5(stats, labels)

    last_5_avg = last_5 if last_5 is not None else season_avg
    projected_line = season_avg * factor
    confidence = _confidence(
        season_avg=season_avg,
        last_5_avg=last_5_avg,
        position=record.get("position"),
        team=record.get("team"),
        market=market_key,
    )
    return {
        "player": name,
        "market": market_key,
        "sport": sport_key,
        "projected_line": round(projected_line, 2),
        "season_avg": round(season_avg, 2),
        "last_5_avg": round(last_5_avg, 2),
        "matchup_factor": round(factor, 4),
        "confidence": confidence,
        "basis": ("season average" if last_5 is None else "season average + last-5 recency"),
        "source": "projection",
    }
