"""Player stats — ESPN game logs, averages, and hot/cold streak detection.

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
import statistics
from typing import Any

from datasets.sports_data.player_common import (
    ESPN_GAMELOG,
    ESPN_SEARCH,
    _espn_pair,
    _resolve_one,
)
from datasets.sports_data.props_http import fetch_json
from datasets.sports_data.props_tables import _short_slug
from datasets.sports_data.props_util import _as_text, _to_float

logger = logging.getLogger(__name__)

_STREAK_STATS: dict[str, tuple[str, ...]] = {
    "nba": ("PTS", "REB", "AST", "FGM", "FG3M", "MIN"),
    "wnba": ("PTS", "REB", "AST"),
    "nfl": ("PASSYDS", "RUSHYDS", "RECYDS", "TD"),
    "mlb": ("H", "HR", "RBI", "SO"),
    "nhl": ("G", "A", "SOG", "PIM"),
}


def _parse_gamelog(payload: dict[str, Any], games: int) -> list[dict[str, Any]]:
    """Parse an ESPN gamelog payload into per-game stat dicts (newest last)."""
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    per_game: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stats = entry.get("stats")
        if not isinstance(stats, list):
            continue
        game = entry.get("game")
        game_info = game.get("result") if isinstance(game, dict) else None
        record: dict[str, Any] = {
            "date": _as_text(game.get("date")) if isinstance(game, dict) else None,
            "opponent": _as_text(game.get("opponent", {}).get("displayName"))
            if isinstance(game, dict) and isinstance(game.get("opponent"), dict)
            else None,
            "result": _as_text(game_info) if game_info else None,
        }
        for label, value in zip(labels, stats, strict=False):
            label_text = _as_text(label)
            if label_text:
                record[label_text] = _to_float(value) if _to_float(value) is not None else value
        per_game.append(record)
    return per_game[-max(1, games) :]


def _averages(per_game: list[dict[str, Any]]) -> dict[str, float]:
    """Numeric per-stat averages across the game-log window."""
    totals: dict[str, list[float]] = {}
    for game in per_game:
        for key, value in game.items():
            if key in {"date", "opponent", "result"}:
                continue
            number = _to_float(value)
            if number is not None:
                totals.setdefault(key, []).append(number)
    return {key: round(statistics.fmean(vals), 2) for key, vals in totals.items() if vals}


def _season_average(payload: dict[str, Any], stat_label: str) -> float | None:
    """Season-average for one stat label from the gamelog payload, if present."""
    season = payload.get("season")
    if not isinstance(season, dict):
        return None
    labels = season.get("labels")
    stats = season.get("statistics") or season.get("stats")
    if not isinstance(labels, list) or not isinstance(stats, list):
        return None
    for label, value in zip(labels, stats, strict=False):
        if _as_text(label) == stat_label:
            return _to_float(value)
    return None


def _trend_flag(recent_avg: float | None, season_avg: float | None, threshold: float = 0.08) -> str:
    """Hot / cold / steady flag from recent-vs-season average delta."""
    if recent_avg is None or season_avg is None or season_avg == 0:
        return "steady"
    delta = (recent_avg - season_avg) / abs(season_avg)
    if delta >= threshold:
        return "hot"
    if delta <= -threshold:
        return "cold"
    return "steady"


async def _resolve_athlete(
    name: str, espn_sport: str, espn_league: str
) -> tuple[str, str | None] | None:
    """Resolve a player name to (athlete_id, team_name) via ESPN search."""
    payload = await fetch_json(
        ESPN_SEARCH,
        {
            "query": name,
            "type": "player",
            "sport": espn_sport,
            "league": espn_league,
            "limit": "5",
        },
    )
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").lower() not in {"player", "athlete"}:
            continue
        athlete_id = _as_text(item.get("id"))
        if not athlete_id:
            continue
        team = None
        relationships = item.get("teamRelationships")
        if isinstance(relationships, list):
            for rel in relationships:
                if isinstance(rel, dict) and _as_text(rel.get("displayName")):
                    team = _as_text(rel.get("displayName"))
                    break
        return athlete_id, team
    return None


async def get_player_recent_stats(
    player_name: str, sport: str = "nba", games: int = 10
) -> dict[str, Any]:
    """Last N games of stats for a player, with averages and hot/cold trend.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).
        games: Number of recent games (1-30, default 10).

    Returns:
        A dict::

            {
                "player": "LeBron James",
                "sport": "nba",
                "games_requested": 10,
                "games_found": 10,
                "per_game": [
                    {"date": "...", "opponent": "...", "result": "W 112-108",
                     "PTS": 27.0, "REB": 8.0, "AST": 6.0, "MIN": 35.0, ...},
                    ...
                ],
                "averages": {"PTS": 25.4, "REB": 7.8, ...},
                "trend": {"PTS": "hot", "REB": "steady", ...},
                "source": "espn",
            }

        ``{}`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_recent_stats(player_name, sport, games)
    except Exception:
        logger.exception(
            "sports_player_intel_recent_stats_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return {}


async def _get_player_recent_stats(player_name: str, sport: str, games: int) -> dict[str, Any]:
    name = str(player_name or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    found = await _resolve_athlete(name, espn_sport, espn_league)
    if found is None:
        return {}
    athlete_id, team = found
    clamped = max(1, min(int(games), 30))
    payload = await fetch_json(
        ESPN_GAMELOG.format(sport=espn_sport, league=espn_league, id=athlete_id)
    )
    if not isinstance(payload, dict):
        return {}
    per_game = _parse_gamelog(payload, clamped)
    averages = _averages(per_game)
    trend: dict[str, str] = {}
    for stat_label, recent_avg in averages.items():
        season_avg = _season_average(payload, stat_label)
        trend[stat_label] = _trend_flag(recent_avg, season_avg)
    return {
        "player": name,
        "team": team,
        "sport": _short_slug(slug),
        "games_requested": clamped,
        "games_found": len(per_game),
        "per_game": per_game,
        "averages": averages,
        "trend": trend,
        "source": "espn",
    }


def _compute_streaks(
    per_game: list[dict[str, Any]],
    averages: dict[str, float],
    season_averages: dict[str, float],
) -> dict[str, Any]:
    """Condense a game log into streak / trend records.

    ``current_streak`` counts consecutive games (newest first) above
    (``hot``) or below (``cold``) the season average for the player's
    primary stat; ``prop_trend`` counts overs/unders hit versus the
    season average across the tracked stats.
    """
    primary = next((label for label in ("PTS", "PASSYDS", "H", "G") if label in averages), None)
    if not averages:
        primary = None
    current_streak: dict[str, Any] = {"type": "none", "games": 0, "stat": primary}
    if primary and primary in season_averages and per_game:
        season_avg = season_averages[primary]
        streak_type: str | None = None
        count = 0
        for game in reversed(per_game):  # newest first
            value = _to_float(game.get(primary))
            if value is None or season_avg == 0:
                break
            direction = "hot" if value > season_avg else "cold"
            if streak_type is None:
                streak_type = direction
            elif direction != streak_type:
                break
            count += 1
        if streak_type and count >= 2:
            current_streak = {"type": streak_type, "games": count, "stat": primary}

    avg_vs_season: dict[str, dict[str, float | str]] = {}
    for stat_label, recent in averages.items():
        season = season_averages.get(stat_label)
        if season is None:
            continue
        avg_vs_season[stat_label] = {
            "recent": recent,
            "season": season,
            "delta": round(recent - season, 2),
            "flag": _trend_flag(recent, season),
        }

    overs = unders = total = 0
    for stat_label, season in season_averages.items():
        if season is None or season == 0:
            continue
        for game in per_game:
            value = _to_float(game.get(stat_label))
            if value is None:
                continue
            total += 1
            if value > season:
                overs += 1
            elif value < season:
                unders += 1
    if total:
        over_rate = overs / total
        prop_trend = "over" if over_rate >= 0.6 else "under" if over_rate <= 0.4 else "mixed"
    else:
        over_rate = None
        prop_trend = "unknown"

    return {
        "current_streak": current_streak,
        "avg_vs_season": avg_vs_season,
        "prop_trend": prop_trend,
        "over_rate": round(over_rate, 2) if over_rate is not None else None,
        "games_sampled": total,
    }


async def get_player_streaks(player_name: str, sport: str = "nba") -> dict[str, Any]:
    """Hot/cold streak detection for a player versus season averages.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A dict::

            {
                "player": "LeBron James",
                "sport": "nba",
                "current_streak": {"type": "hot", "games": 4, "stat": "PTS"},
                "avg_vs_season": {
                    "PTS": {"recent": 28.1, "season": 25.4, "delta": 2.7,
                            "flag": "hot"},
                    ...
                },
                "prop_trend": "over",   # over / under / mixed / none
                "over_rate": 0.68,      # share of games above season avg
                "games_sampled": 57,
                "source": "espn",
            }

        ``{}`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_streaks(player_name, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_streaks_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return {}


async def _get_player_streaks(player_name: str, sport: str) -> dict[str, Any]:
    name = str(player_name or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    found = await _resolve_athlete(name, espn_sport, espn_league)
    if found is None:
        return {}
    athlete_id, team = found
    payload = await fetch_json(
        ESPN_GAMELOG.format(sport=espn_sport, league=espn_league, id=athlete_id)
    )
    if not isinstance(payload, dict):
        return {}
    per_game = _parse_gamelog(payload, 30)
    averages = _averages(per_game)
    season_averages = {
        label: value for label in averages if (value := _season_average(payload, label)) is not None
    }
    result = _compute_streaks(per_game, averages, season_averages)
    result.update(
        {
            "player": name,
            "team": team,
            "sport": _short_slug(slug),
            "source": "espn",
        }
    )
    return result
