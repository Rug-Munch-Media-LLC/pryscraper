"""Lineups — active/projected lineups, injuries, minutes projection (ESPN).

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

from datasets.sports_data.player_common import (
    _GAME_TIME,
    _MINUTES_HAIRCUT,
    _OUT_STATUSES,
    ESPN_SUMMARY,
    _resolve_one,
    _resolve_team,
)
from datasets.sports_data.props_http import fetch_json
from datasets.sports_data.props_tables import _short_slug
from datasets.sports_data.props_util import _as_text, _to_float

logger = logging.getLogger(__name__)


def _athlete_brief(athlete: Any) -> dict[str, Any]:
    """Compact {id, name, position} from an ESPN athlete object."""
    if not isinstance(athlete, dict):
        return {}
    return {
        "id": _as_text(athlete.get("id")),
        "name": _as_text(athlete.get("displayName")) or _as_text(athlete.get("fullName")),
        "position": _as_text(athlete.get("position", {}).get("abbreviation"))
        if isinstance(athlete.get("position"), dict)
        else None,
    }


def _minutes_from_stats(stat_rows: Any, labels: Any) -> float | None:
    """Extract minutes played from an ESPN boxscore stat row."""
    if not isinstance(stat_rows, list) or not isinstance(labels, list):
        return None
    for row in stat_rows:
        if not isinstance(row, list):
            continue
        for label, value in zip(labels, row, strict=False):
            if str(label).strip().upper() in {"MIN", "MPG", "MINS"}:
                minutes = _to_float(value)
                if minutes is not None:
                    return minutes
    return None


def _parse_summary_lineups(summary: dict[str, Any], competitor: dict[str, Any]) -> dict[str, Any]:
    """Parse an ESPN game summary into the lineup record shape."""
    team_id = _as_text(competitor.get("id"))
    team_name = None
    team_obj = competitor.get("team")
    if isinstance(team_obj, dict):
        team_name = _as_text(team_obj.get("displayName"))

    starters: list[dict[str, Any]] = []
    bench: list[dict[str, Any]] = []
    probable: list[dict[str, Any]] = []
    minutes_projection: dict[str, float] = {}

    boxscore = summary.get("boxscore")
    players = boxscore.get("players") if isinstance(boxscore, dict) else None
    if isinstance(players, list):
        for team_block in players:
            if not isinstance(team_block, dict):
                continue
            block_team = team_block.get("team")
            block_id = _as_text(block_team.get("id")) if isinstance(block_team, dict) else None
            if team_id and block_id and block_id != team_id:
                continue
            entries = team_block.get("entries") or team_block.get("players")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete")
                brief = _athlete_brief(athlete)
                if not brief.get("name"):
                    continue
                stats = entry.get("stats")
                labels = entry.get("labels")
                minutes = _minutes_from_stats(stats, labels)
                if minutes is not None:
                    minutes_projection[str(brief["name"])] = round(minutes, 1)
                starter_flag = entry.get("starter")
                if starter_flag is True or starter_flag == "true":
                    starters.append(brief)
                else:
                    bench.append(brief)

    # Probable pitchers (MLB) / probable starters surface on the summary.
    probables = summary.get("probables")
    if isinstance(probables, list):
        for prob in probables:
            if not isinstance(prob, dict):
                continue
            player = prob.get("player")
            if isinstance(player, dict):
                brief = _athlete_brief(player)
                if brief.get("name"):
                    probable.append(brief)

    # Injury report — split into game-time vs out buckets.
    questionable: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    injuries = summary.get("injuries")
    if isinstance(injuries, list):
        for team_injuries in injuries:
            if not isinstance(team_injuries, dict):
                continue
            inj_team = team_injuries.get("team")
            inj_team_id = _as_text(inj_team.get("id")) if isinstance(inj_team, dict) else None
            if team_id and inj_team_id and inj_team_id != team_id:
                continue
            entries = team_injuries.get("injuries")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete")
                brief = _athlete_brief(athlete)
                if not brief.get("name"):
                    continue
                status = str(entry.get("status") or "").strip().lower()
                brief["status"] = status
                if status in _OUT_STATUSES:
                    out.append(brief)
                    minutes_projection[str(brief["name"])] = 0.0
                elif status in _GAME_TIME:
                    questionable.append(brief)
                    base = minutes_projection.get(str(brief["name"]))
                    if base:
                        minutes_projection[str(brief["name"])] = round(base * _MINUTES_HAIRCUT, 1)

    header = summary.get("header")
    headline = _as_text(header.get("headline")) if isinstance(header, dict) else None

    return {
        "team": team_name,
        "team_id": team_id,
        "sport": None,  # filled by caller
        "event": headline,
        "event_id": _as_text(summary.get("id")),
        "starters": starters,
        "bench": bench,
        "probable": probable,
        "questionable": questionable,
        "out": out,
        "minutes_projection": minutes_projection,
        "source": "espn",
    }


async def get_lineups(team: str, sport: str = "nba") -> dict[str, Any]:
    """Active/projected lineup, injury report, and minutes projection for a team.

    Args:
        team: Team name (e.g. ``"Lakers"``, ``"Boston Celtics"``).
        sport: Sport slug (``nba``, ``nfl``, ``mlb``, ``nhl``, ...).

    Returns:
        A dict::

            {
                "team": "Los Angeles Lakers",
                "team_id": "13",
                "sport": "nba",
                "event": "Lakers vs Celtics",
                "event_id": "401772301",
                "starters": [{"id": "...", "name": "...", "position": "PG"}, ...],
                "bench": [...],
                "probable": [...],        # MLB probable pitchers
                "questionable": [...],    # game-time-decision injuries
                "out": [...],             # ruled out
                "minutes_projection": {"LeBron James": 34.5, ...},
                "source": "espn",
            }

        ``{}`` on failure, unknown team, or no upcoming event. Never raises.
    """
    try:
        return await _get_lineups(team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_lineups_crashed", extra={"team": team, "sport": sport}
        )
        return {}


async def _get_lineups(team: str, sport: str) -> dict[str, Any]:
    name = str(team or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport) or ""
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    resolved = await _resolve_team(name, slug)
    if resolved is None:
        return {}
    event, competitor, espn_sport, espn_league = resolved
    event_id = _as_text(event.get("id"))
    if not event_id:
        return {}
    summary = await fetch_json(
        ESPN_SUMMARY.format(sport=espn_sport, league=espn_league), {"event": event_id}
    )
    if not isinstance(summary, dict):
        return {}
    record = _parse_summary_lineups(summary, competitor)
    record["sport"] = _short_slug(slug)
    return record
