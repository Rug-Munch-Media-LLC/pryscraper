"""Pry - MCP tool definitions: game-context tools (weather, rest, travel).

Exposes the :mod:`datasets.sports_data.game_context` dataset as MCP tool
schemas (``PRY_TOOLS``) for the Pry tool registry. All tools are
read-only, free-data (Open-Meteo + ESPN), and degrade to ``{}`` on
upstream failure.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

_SPORTS = ["nfl", "nba", "mlb", "nhl", "ncaaf", "ncaab", "wnba"]

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_game_weather",
        "description": (
            "Get current weather at a game venue (temperature, wind, "
            "precipitation, humidity, visibility) via Open-Meteo. Use before "
            "lock to check outdoor-game conditions, e.g. 'how windy is it in "
            "Chicago right now?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {
                    "type": "number",
                    "description": "Venue latitude (e.g. 41.88 for Chicago)",
                },
                "lon": {
                    "type": "number",
                    "description": "Venue longitude (e.g. -87.63 for Chicago)",
                },
            },
            "required": ["lat", "lon"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "temp_f": {"type": "number"},
                "wind_mph": {"type": "number"},
                "precipitation": {"type": "number"},
                "humidity": {"type": "number"},
                "visibility": {"type": "number"},
                "conditions_summary": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "pry_weather_impact",
        "description": (
            "Translate venue weather into betting impact: wind/temp/precip "
            "bands, a total (points) adjustment, and pass-vs-run game "
            "lean. Use for NFL/NCAA outdoor totals and spread edges, e.g. "
            "'does the wind favor the under tonight?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Venue latitude"},
                "lon": {"type": "number", "description": "Venue longitude"},
                "sport": {
                    "type": "string",
                    "enum": _SPORTS,
                    "default": "nfl",
                    "description": "Sport context (default nfl)",
                },
            },
            "required": ["lat", "lon"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "sport": {"type": "string"},
                "wind_impact": {"type": "string", "enum": ["low", "med", "high", "unknown"]},
                "temp_impact": {"type": "string", "enum": ["cold", "heat", "neutral", "unknown"]},
                "precip_impact": {"type": "string", "enum": ["low", "med", "high", "unknown"]},
                "total_adjustment": {"type": "number"},
                "pass_game_impact": {"type": "string"},
                "run_game_impact": {"type": "string"},
                "weather": {"type": "object"},
            },
            "required": [],
        },
    },
    {
        "name": "pry_game_context",
        "description": (
            "Full game-context bundle for a matchup: venue weather, "
            "weather impact on scoring, rest days / back-to-back flags "
            "(ESPN), and travel distance / time-zone / altitude change. "
            "Use for situational edges, e.g. 'any rest or travel edge for "
            "the Nuggets at the Lakers?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Venue latitude"},
                "lon": {"type": "number", "description": "Venue longitude"},
                "home_team": {
                    "type": "string",
                    "description": "Home team name (e.g. 'Denver Nuggets')",
                },
                "away_team": {
                    "type": "string",
                    "description": "Away team name (e.g. 'Los Angeles Lakers')",
                },
                "sport": {
                    "type": "string",
                    "enum": _SPORTS,
                    "default": "nfl",
                    "description": "Sport context (default nfl)",
                },
            },
            "required": ["lat", "lon", "home_team", "away_team"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "sport": {"type": "string"},
                "home_team": {"type": "string"},
                "away_team": {"type": "string"},
                "weather": {"type": "object"},
                "weather_impact": {"type": "object"},
                "rest": {
                    "type": "object",
                    "properties": {
                        "home_rest_days": {"type": "integer"},
                        "away_rest_days": {"type": "integer"},
                        "rest_advantage": {"type": "integer"},
                        "home_back_to_back": {"type": "boolean"},
                        "away_back_to_back": {"type": "boolean"},
                    },
                },
                "travel": {
                    "type": "object",
                    "properties": {
                        "travel_distance": {"type": "integer"},
                        "time_zone_change": {"type": "integer"},
                        "altitude_change": {"type": "integer"},
                    },
                },
            },
            "required": [],
        },
    },
]

_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_game_weather": (("game_context", ("get_game_weather",)),),
    "pry_weather_impact": (("game_context", ("get_weather_impact",)),),
    "pry_game_context": (("game_context", ("get_game_context",)),),
}
