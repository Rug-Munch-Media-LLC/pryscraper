"""Pry - MCP tool definition: futures / championship odds tool.

Holds the ``PRY_TOOLS`` schema for ``pry_futures`` — long-term markets
(Super Bowl winner, NBA MVP, league champions, award winners) with
implied probability, best-odds aggregation, and vig detection.
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
        "name": "pry_futures",
        "description": (
            "Get futures and championship odds across sportsbooks — Super Bowl "
            "winner, NBA MVP, league champions, award winners. Includes implied "
            "probability, best odds aggregation, and vig detection across all "
            "books. "
            "Use for long-term market research, e.g. 'who is favored to win the "
            "Super Bowl and at what price across books?' or call with "
            "sport='nba' to see every NBA futures market."
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
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": ("Maximum number of futures market records (default: 20)"),
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
                            "market_id": {"type": "string"},
                            "market_name": {"type": "string"},
                            "sport": {"type": "string"},
                            "outcomes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "price": {"type": "number"},
                                        "implied_prob": {"type": "number"},
                                        "book": {"type": "string"},
                                    },
                                },
                            },
                            "best_odds": {"type": "number"},
                            "best_book": {"type": "string"},
                            "total_implied_prob": {"type": "number"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]

# Candidate registry (guarded): maps pry_futures to the futures module's
# public callables, tried in order by the dispatcher.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_futures": (
        ("futures", ("get_futures_odds",)),
        ("futures_odds", ("get_futures_odds",)),
    ),
}
