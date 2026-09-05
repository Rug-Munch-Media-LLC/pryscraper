"""Matchup props — both teams' props with defensive-ranking context.

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
from urllib.parse import quote

from datasets.sports_data.odds import _SPORTS
from datasets.sports_data.player_common import (
    ESPN_SCOREBOARD,
    ESPN_TEAM_STATS,
    _espn_pair,
    _event_competitors,
    _find_matchup_event,
    _resolve_one,
)
from datasets.sports_data.player_props import _annotate_movement, _map_all_player_props
from datasets.sports_data.props_http import (
    ODDS_API_REGIONS,
    ODDS_BASE,
    api_key,
    fetch_json,
)
from datasets.sports_data.props_tables import _PROP_MARKETS, _short_slug
from datasets.sports_data.props_util import _as_text, _to_float

logger = logging.getLogger(__name__)

# Default prop markets per sport come from data/props.json (prop_markets);
# the matchup defensive context covers the core counting stats.
_DEFENSE_MARKETS: dict[str, tuple[str, ...]] = {
    "nba": ("player_points", "player_rebounds", "player_assists", "player_threes"),
    "wnba": ("player_points", "player_rebounds", "player_assists"),
    "nfl": ("player_pass_yds", "player_rush_yds", "player_recv_yds"),
    "mlb": ("player_hits", "player_home_runs", "player_rbis"),
    "nhl": ("player_points", "player_shots_on_goal"),
}


def _defense_grade(rank: int | None) -> str | None:
    """Human defensive grade from a league rank (1 = best defense)."""
    if rank is None:
        return None
    if rank <= 8:
        return "tough"
    if rank >= 22:
        return "soft"
    return "average"


async def _team_defensive_ranks(
    team_id: str | None, espn_sport: str, espn_league: str
) -> dict[str, int | None]:
    """Best-effort defensive rank context for one team (per stat category).

    ESPN's public team-stats feed exposes opponent categories; ranks are
    derived by comparing the team's opponent average against the league
    scoreboard teams is out of scope here — we return the raw opponent
    stats and let the caller annotate. Returns a label -> rank map where
    ranks are approximated from the team's defensive stats when present.
    """
    if not team_id:
        return {}
    payload = await fetch_json(
        ESPN_TEAM_STATS.format(sport=espn_sport, league=espn_league, team_id=team_id)
    )
    if not isinstance(payload, dict):
        return {}
    ranks: dict[str, int | None] = {}
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return ranks
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        display_names = cat.get("displayNames")
        statistics_list = cat.get("statistics")
        if (
            isinstance(display_names, list)
            and isinstance(statistics_list, list)
            and statistics_list
        ):
            latest = statistics_list[-1]
            if isinstance(latest, dict) and isinstance(latest.get("stats"), list):
                for label, _value, rank in zip(
                    display_names, latest["stats"], latest.get("perGameRanks", []), strict=False
                ):
                    label_text = _as_text(label)
                    rank_value = _to_float(rank)
                    if label_text and rank_value is not None:
                        ranks[label_text] = int(rank_value)
    return ranks


async def get_props_vs_matchup(
    home_team: str, away_team: str, sport: str = "nba"
) -> dict[str, Any]:
    """All player props for a matchup, with defensive-ranking context.

    Args:
        home_team: Home team name (e.g. ``"Lakers"``).
        away_team: Away team name (e.g. ``"Celtics"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A dict::

            {
                "sport": "nba",
                "event": "Celtics @ Lakers",
                "event_id": "401772301",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "props": [ ...prop records for both teams... ],
                "defense": {
                    "Los Angeles Lakers": {
                        "player_points": {"rank": 5, "grade": "tough"},
                        ...
                    },
                    ...
                },
                "source": "the_odds_api",
            }

        ``{}`` on failure, unknown teams, or no Odds API key. Never raises.
    """
    try:
        return await _get_props_vs_matchup(home_team, away_team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_matchup_crashed",
            extra={"home": home_team, "away": away_team, "sport": sport},
        )
        return {}


async def _get_props_vs_matchup(home_team: str, away_team: str, sport: str) -> dict[str, Any]:
    home = str(home_team or "").strip()
    away = str(away_team or "").strip()
    if not home or not away:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    scoreboard = await fetch_json(ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league))
    if not isinstance(scoreboard, dict):
        return {}
    event = _find_matchup_event(scoreboard, home, away)
    if event is None:
        return {}
    competitors = _event_competitors(event)
    if len(competitors) < 2:
        return {}

    def _team_label(competitor: dict[str, Any]) -> str | None:
        team_obj = competitor.get("team")
        if isinstance(team_obj, dict):
            return _as_text(team_obj.get("displayName")) or _as_text(team_obj.get("name"))
        return None

    home_name = _team_label(competitors[0]) or home
    away_name = _team_label(competitors[1]) or away
    event_id = _as_text(event.get("id"))
    if not event_id:
        return {}

    key = api_key()
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    records: list[dict[str, Any]] = []
    if key and market_keys:
        odds_key, _espn = _SPORTS[slug]
        payload = await fetch_json(
            f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
            {
                "apiKey": key,
                "regions": ODDS_API_REGIONS,
                "markets": ",".join(market_keys),
                "oddsFormat": "decimal",
            },
        )
        if isinstance(payload, dict):
            records = _map_all_player_props(payload, slug, None)
            records = _annotate_movement(records)

    # Defensive context per team from ESPN team stats (best effort).
    defense: dict[str, dict[str, dict[str, Any]]] = {}
    for competitor, label in ((competitors[0], home_name), (competitors[1], away_name)):
        team_obj = competitor.get("team")
        team_id = _as_text(team_obj.get("id")) if isinstance(team_obj, dict) else None
        ranks = await _team_defensive_ranks(team_id, espn_sport, espn_league)
        context: dict[str, dict[str, Any]] = {}
        for market_key in _defense_markets(slug):
            rank = _match_defense_rank(market_key, ranks)
            if rank is not None:
                context[market_key] = {"rank": rank, "grade": _defense_grade(rank)}
        defense[label or ""] = context

    return {
        "sport": _short_slug(slug),
        "event": f"{away_name} @ {home_name}",
        "event_id": event_id,
        "home_team": home_name,
        "away_team": away_name,
        "props": records,
        "defense": defense,
        "source": "the_odds_api" if records else "espn",
    }


def _defense_markets(slug: str) -> tuple[str, ...]:
    """Core prop markets to annotate with defensive context for a sport."""
    return _DEFENSE_MARKETS.get(_short_slug(slug), ())


def _match_defense_rank(market_key: str, ranks: dict[str, int | None]) -> int | None:
    """Best-effort defensive rank for a prop market from ESPN stat labels."""
    fragment = market_key.removeprefix("player_").replace("_", " ").casefold()
    for label, rank in ranks.items():
        if rank is None:
            continue
        if fragment and fragment in label.casefold():
            return rank
    return None
