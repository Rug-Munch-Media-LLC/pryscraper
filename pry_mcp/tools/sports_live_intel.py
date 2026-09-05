"""Pry - MCP tool definitions: live in-game intelligence tools.

Live games / game state / win probability / scoring breakdown / betting
impact schemas, backed by ``datasets.sports_data.live_intel`` (ESPN
public scoreboards, no key).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

_SPORT_DESCRIPTION = "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, cfl (default: nba)"

_EVENT_ID_DESCRIPTION = "ESPN event id (from pry_live_games). Required."

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_live_games",
        "description": (
            "Every in-progress game on a sport's slate right now, from ESPN's free "
            "public scoreboard: event_id, home/away, live scores, quarter, "
            "time remaining, status. Entry point for the other live tools — "
            "grab an event_id here. Example: 'what NBA games are live?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "home": {"type": "string"},
                "away": {"type": "string"},
                "home_score": {"type": "number"},
                "away_score": {"type": "number"},
                "quarter": {"type": "integer"},
                "time_remaining": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    },
    {
        "name": "pry_live_game_state",
        "description": (
            "Full live state for one game: score, quarter, clock, possession, "
            "momentum (last five possessions when available), pace, scoring "
            "rate, remaining timeouts. "
            "Example: 'who has the ball and how fast is this game scoring?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": _EVENT_ID_DESCRIPTION,
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "home": {"type": "object"},
                "away": {"type": "object"},
                "quarter": {"type": "integer"},
                "time_remaining": {"type": "string"},
                "possession": {"type": ["string", "null"]},
                "momentum": {"type": "object"},
                "pace": {"type": "object"},
                "scoring_rate": {"type": "number"},
                "timeouts": {"type": "object"},
            },
        },
    },
    {
        "name": "pry_live_win_probability",
        "description": (
            "Live win probability for one game: home/away chances (ESPN's model "
            "when published, else a lead-vs-time heuristic), projected final "
            "scores, projected total, over/under probability vs the posted "
            "total, spread-cover probabilities. Example: 'who wins this game?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": _EVENT_ID_DESCRIPTION,
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "home_win_probability": {"type": "number"},
                "away_win_probability": {"type": "number"},
                "projected_home_score": {"type": "number"},
                "projected_away_score": {"type": "number"},
                "projected_total": {"type": "number"},
                "over_probability": {"type": ["number", "null"]},
                "spread_cover_probability": {"type": "object"},
            },
        },
    },
    {
        "name": "pry_live_scoring",
        "description": (
            "Scoring breakdown for one live game: per-quarter scores for both "
            "teams, lead changes, ties and quarter-by-quarter scoring runs. "
            "Example: 'how many lead changes tonight?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": _EVENT_ID_DESCRIPTION,
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "quarters": {"type": "array", "items": {"type": "object"}},
                "lead_changes": {"type": "integer"},
                "ties": {"type": "integer"},
                "scoring_runs": {"type": "array", "items": {"type": "object"}},
                "current_margin": {"type": "number"},
            },
        },
    },
    {
        "name": "pry_live_betting_impact",
        "description": (
            "Live betting impact for one game: current margin vs the posted "
            "spread, pace-based total projection vs the posted total, and "
            "live value/arb opportunities (spread edge >= 3 pts, total edge "
            ">= 8 pts). Example: 'any live value on this game?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": _EVENT_ID_DESCRIPTION,
                },
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "event": {"type": "string"},
                "current_margin": {"type": "number"},
                "posted_spread": {"type": ["number", "null"]},
                "posted_total": {"type": ["number", "null"]},
                "pace_projected_total": {"type": "number"},
                "arb_opportunities": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
]
