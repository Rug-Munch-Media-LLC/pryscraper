"""Pry - MCP tool definitions: sports data-retrieval tools (scores, injuries).

Split from the former ``pry_mcp/tools/sports.py`` god file. Holds the
data-retrieval tool schemas (``PRY_TOOLS``) and the guarded candidate
registry (``_SPORTS_TOOL_FNS``) for scores and injury reports.
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
        "name": "pry_injuries",
        "description": (
            "Get the current injury report for a sport or team: player, team, "
            "injury detail, and status (out/questionable/active). "
            "Use to adjust betting models or fantasy lineups before lock, e.g. "
            "'who is out for the Celtics tonight?' or call with sport='nfl' for "
            "the full league injury report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "team": {
                    "type": "string",
                    "description": (
                        "Team name to filter by (e.g., 'Celtics', 'Chiefs'); omit for every team"
                    ),
                },
            },
            "required": [],
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
                            "team": {"type": "string"},
                            "sport": {"type": "string"},
                            "injury": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "team": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_scores",
        "description": (
            "Get final or live scores for one or more sports on a given day from "
            "ESPN public scoreboards (free, no quota, high-frequency safe). "
            "Use to check results or power a scores widget, e.g. 'what were the "
            "NBA scores on 20260815?' or call with sport='mlb' and date='today' "
            "for today's baseball scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default: nba + nfl + epl)"
                    ),
                },
                "date": {
                    "type": "string",
                    "default": "today",
                    "description": ("Date: 'today' (default), YYYYMMDD, or YYYY-MM-DD"),
                },
            },
            "required": [],
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
                            "sport": {"type": "string"},
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "home_score": {"type": "string"},
                            "away_score": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# ── Sports data-retrieval candidate registry (guarded) ────────────────
# Candidate public function names for the sports_data data modules. The
# scores module has landed (get_scores); injuries lands from a parallel agent.
# Each tool maps to one or more (module, candidate-callables) options tried in
# order, so the dispatcher resolves whichever module/function the landed code
# actually exposes.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_scores": (("scores", ("get_scores",)),),
    "pry_injuries": (("injuries", ("get_injuries", "list_injuries", "injury_report")),),
}
