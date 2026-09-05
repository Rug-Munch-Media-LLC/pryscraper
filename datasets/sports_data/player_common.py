"""Shared transport and resolution helpers for the player-intel submodules.

ESPN public API endpoints (site.api / site.web.api — no key required),
injury-status constants, and team/event resolution against the ESPN
scoreboard. Used by :mod:`player_lineups`, :mod:`player_props`,
:mod:`player_stats`, and :mod:`player_matchup`.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import statistics
from typing import Any

from datasets.sports_data.odds import _SPORTS
from datasets.sports_data.props_http import fetch_json
from datasets.sports_data.props_util import _as_text

# ── ESPN endpoints (site.api / site.web.api — no key required) ─────────
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
ESPN_SCOREBOARD = ESPN_SITE + "/scoreboard"
ESPN_SUMMARY = ESPN_SITE + "/summary"
ESPN_ROSTER = ESPN_SITE + "/teams/{team_id}/roster"
ESPN_TEAM_STATS = ESPN_SITE + "/teams/{team_id}/stats"
ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_GAMELOG = (
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/gamelog"
)

# Injury statuses that mean "will not play" (minutes projected to 0).
_OUT_STATUSES = {"out", "out for season", "suspended", "injured reserve", "nwt"}
# Statuses that mean "game-time decision" (minutes haircut).
_GAME_TIME = {"questionable", "doubtful", "day-to-day", "game time decision"}

# Minutes haircut applied to players returning from a game-time-decision
# injury (conservative projection until the status clears).
_MINUTES_HAIRCUT = 0.75


# ── Small helpers ──────────────────────────────────────────────────────
def _espn_pair(slug: str) -> tuple[str, str] | None:
    """ESPN (sport, league) for a canonical sport slug, or None."""
    entry = _SPORTS.get(slug)
    if not entry or entry[1] is None:
        return None
    return entry[1]


def _name_matches(candidate: str | None, needle: str) -> bool:
    """Case-insensitive substring match on a player/team name."""
    if not candidate:
        return False
    return needle.casefold() in candidate.casefold()


def _median(values: list[float]) -> float | None:
    """Median of a non-empty list, else None."""
    return statistics.median(values) if values else None


def _movement(line: float | None, consensus: float | None) -> str:
    """Cross-book movement signal for one line vs the consensus median."""
    if line is None or consensus is None:
        return "steady"
    if line > consensus:
        return "up"
    if line < consensus:
        return "down"
    return "steady"


def _resolve_one(sport: str) -> str | None:
    """Resolve a sport param to exactly one canonical slug (or None)."""
    raw = str(sport or "").strip().lower()
    if raw in _SPORTS:
        return raw
    return None


# ── Team / event resolution (ESPN scoreboard) ──────────────────────────
def _find_team_event(
    scoreboard: dict[str, Any], needle: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find (event, competitor) for a team name in an ESPN scoreboard payload."""
    events = scoreboard.get("events")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        competitors = _event_competitors(event)
        for competitor in competitors:
            team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
            if _name_matches(_as_text(team.get("displayName")), needle) or _name_matches(
                _as_text(team.get("name")), needle
            ):
                return event, competitor
    return None


def _find_matchup_event(scoreboard: dict[str, Any], home: str, away: str) -> dict[str, Any] | None:
    """Find the event where ``away`` plays at ``home`` (either order accepted)."""
    events = scoreboard.get("events")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        competitors = _event_competitors(event)
        names = []
        for competitor in competitors:
            team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
            names.append(
                (_as_text(team.get("displayName")) or _as_text(team.get("name")) or "").casefold()
            )
        if _name_matches(" ".join(names), home) and _name_matches(" ".join(names), away):
            return event
    return None


def _event_competitors(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an ESPN event's competitions[0].competitors."""
    competitions = event.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        return []
    first = competitions[0]
    competitors = first.get("competitors") if isinstance(first, dict) else None
    if not isinstance(competitors, list):
        return []
    return [c for c in competitors if isinstance(c, dict)]


async def _resolve_team(
    team: str, slug: str
) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
    """Resolve a team name to (event, competitor, espn_sport, espn_league)."""
    espn = _espn_pair(slug)
    if espn is None:
        return None
    espn_sport, espn_league = espn
    scoreboard = await fetch_json(ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league))
    if not isinstance(scoreboard, dict):
        return None
    found = _find_team_event(scoreboard, team)
    if found is None:
        return None
    event, competitor = found
    return event, competitor, espn_sport, espn_league
