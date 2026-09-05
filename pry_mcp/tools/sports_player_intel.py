"""Pry - MCP tool definitions: player-intelligence tools (lineups, props, streaks).

The bettor-facing player layer on top of the sports_data engines: who's
starting, who's hurt, what the lines are right now, how the player has
been trending, and how the opponent defends each prop type. Backed by
:mod:`datasets.sports_data.player_intel` (ESPN public APIs + The Odds API).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_lineups",
        "description": (
            "Get the active/projected lineup, injury report, and minutes "
            "projection for a team's next game, from ESPN. Returns starters, "
            "bench, probable pitchers (MLB), questionable/doubtful players "
            "(game-time decisions), ruled-out players, and a per-player "
            "projected-minutes map (season MPG, haircut for players returning "
            "from injury, zero for ruled-out). "
            "Use before betting any player prop to confirm the player is "
            "actually starting and see his projected role, e.g. 'is LeBron "
            "James starting tonight and how many minutes is he projected?' "
            "or call with team='Celtics' to check the full rotation and "
            "injury list before the tip."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "team": {
                    "type": "string",
                    "description": ("Team name, e.g. 'Lakers', 'Boston Celtics', 'Yankees'"),
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, wnba, epl, mls (default: nba)"
                    ),
                },
            },
            "required": ["team"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "team": {"type": "string"},
                        "team_id": {"type": "string"},
                        "sport": {"type": "string"},
                        "event": {"type": "string"},
                        "event_id": {"type": "string"},
                        "starters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "position": {"type": "string"},
                                },
                            },
                        },
                        "bench": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "probable": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "questionable": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            },
                        },
                        "out": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            },
                        },
                        "minutes_projection": {
                            "type": "object",
                            "description": (
                                "Player name -> projected minutes (0 for ruled-out players)"
                            ),
                            "additionalProperties": {"type": "number"},
                        },
                        "source": {"type": "string"},
                    },
                },
                "team": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_player_props_live",
        "description": (
            "Get ALL live player prop lines for one player across every "
            "bookmaker (DraftKings, FanDuel, BetMGM, ...) with a cross-book "
            "line-movement signal. Each record includes the prop type "
            "(points, rebounds, assists, yards, ...), the line, over/under "
            "odds, the book, and movement ('up'/'down'/'steady' versus the "
            "consensus median line across books). Falls back to ESPN "
            "season-average projected lines when no Odds API key is "
            "configured (labelled 'ESPN Estimate', no odds). "
            "Use to shop a player's props across books and spot lines that "
            "have moved, e.g. 'show me every Jayson Tatum prop right now and "
            "which books moved his points line up' or call with "
            "sport='nfl' for a QB's passing props."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Player name, e.g. 'LeBron James'",
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, wnba, epl, mls (default: nba)"
                    ),
                },
            },
            "required": ["player_name"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "player": {"type": "string"},
                            "sport": {"type": "string"},
                            "prop_type": {"type": "string"},
                            "market": {"type": "string"},
                            "line": {"type": "number"},
                            "over_odds": {"type": ["number", "null"]},
                            "under_odds": {"type": ["number", "null"]},
                            "book": {"type": "string"},
                            "movement": {
                                "type": "string",
                                "enum": ["up", "down", "steady"],
                            },
                            "source": {"type": "string"},
                        },
                    },
                },
                "player_name": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_player_stats",
        "description": (
            "Get a player's last N games of stats with per-game lines, "
            "averages, and a hot/cold trend flag per stat versus his season "
            "average, from the ESPN game log. "
            "Use to check recent form before betting a prop, e.g. 'how has "
            "Nikola Jokic been scoring over his last 10 games — hot or "
            "cold?' or call with games=5 for a short-form window. The "
            "trend map flags each stat 'hot' (recent avg >= 8% above "
            "season), 'cold' (>= 8% below), or 'steady'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Player name, e.g. 'LeBron James'",
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, wnba, epl, mls (default: nba)"
                    ),
                },
                "games": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30,
                    "description": ("Number of recent games to analyze (default: 10, max: 30)"),
                },
            },
            "required": ["player_name"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "player": {"type": "string"},
                        "team": {"type": ["string", "null"]},
                        "sport": {"type": "string"},
                        "games_requested": {"type": "integer"},
                        "games_found": {"type": "integer"},
                        "per_game": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "opponent": {"type": "string"},
                                    "result": {"type": "string"},
                                },
                                "additionalProperties": True,
                            },
                        },
                        "averages": {
                            "type": "object",
                            "description": "Stat label -> recent average",
                            "additionalProperties": {"type": "number"},
                        },
                        "trend": {
                            "type": "object",
                            "description": (
                                "Stat label -> hot / cold / steady versus season average"
                            ),
                            "additionalProperties": {
                                "type": "string",
                                "enum": ["hot", "cold", "steady"],
                            },
                        },
                        "source": {"type": "string"},
                    },
                },
                "player_name": {"type": "string"},
                "sport": {"type": "string"},
                "games": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_props_matchup",
        "description": (
            "Get ALL player props for both teams in a matchup, annotated "
            "with defensive context: how the opposing defense ranks against "
            "each core prop type (points, rebounds, assists, yards, ...) "
            "with a 'tough' (top-8 defense), 'average', or 'soft' "
            "(bottom-8) grade. "
            "Use to find props the matchup favors, e.g. 'show me every prop "
            "for Celtics @ Lakers and which defense is soft against "
            "threes' — the single call that replaces checking the slate, "
            "the injury report, and five books separately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "home_team": {
                    "type": "string",
                    "description": "Home team name, e.g. 'Lakers'",
                },
                "away_team": {
                    "type": "string",
                    "description": "Away team name, e.g. 'Celtics'",
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, wnba, epl, mls (default: nba)"
                    ),
                },
            },
            "required": ["home_team", "away_team"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "sport": {"type": "string"},
                        "event": {"type": "string"},
                        "event_id": {"type": "string"},
                        "home_team": {"type": "string"},
                        "away_team": {"type": "string"},
                        "props": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "player": {"type": "string"},
                                    "sport": {"type": "string"},
                                    "prop_type": {"type": "string"},
                                    "line": {"type": "number"},
                                    "over_odds": {"type": ["number", "null"]},
                                    "under_odds": {"type": ["number", "null"]},
                                    "book": {"type": "string"},
                                    "movement": {
                                        "type": "string",
                                        "enum": ["up", "down", "steady"],
                                    },
                                    "source": {"type": "string"},
                                },
                            },
                        },
                        "defense": {
                            "type": "object",
                            "description": (
                                "Team name -> prop market -> {rank, grade} defensive context"
                            ),
                            "additionalProperties": {
                                "type": "object",
                                "additionalProperties": {
                                    "type": "object",
                                    "properties": {
                                        "rank": {"type": "integer"},
                                        "grade": {
                                            "type": "string",
                                            "enum": ["tough", "average", "soft"],
                                        },
                                    },
                                },
                            },
                        },
                        "source": {"type": "string"},
                    },
                },
                "home_team": {"type": "string"},
                "away_team": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# ── Player-intel candidate registry (guarded) ─────────────────────────
# Maps each tool to the (module, candidate-callables) options the dispatcher
# tries in order, matching the sports_betting.py pattern.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_lineups": (("player_intel", ("get_lineups",)),),
    "pry_player_props_live": (("player_intel", ("get_player_props_live",)),),
    "pry_player_stats": (("player_intel", ("get_player_recent_stats",)),),
    "pry_props_matchup": (("player_intel", ("get_props_vs_matchup",)),),
}
