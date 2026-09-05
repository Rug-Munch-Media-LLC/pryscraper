"""Pry - MCP tool definitions: source-registry / odds aggregation tools.

Split from the former ``pry_mcp/tools/scraping.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_SOURCE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_scrape_methods",
        "description": (
            "List the extraction methods Pry uses to scrape sportsbook odds "
            "pages directly: JSON endpoints, __NEXT_DATA__ (Next.js), __NUXT__, "
            "__INITIAL_STATE__ / _dida_config_, HTML tables, and browser "
            "rendering. "
            "Use to understand how each book in the 112-book registry is reached "
            "and which fallback tiers apply, e.g. 'which books need a browser?' "
            "or to audit the no-paid-API scraping layer before building on it."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "methods": {"type": "array", "items": {"type": "string"}},
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_all_sources",
        "description": (
            "Aggregate one event's odds from every reachable source at once: "
            "The Odds API (free tier), ESPN, OddsPortal, Bovada, BetOnline, and "
            "the 112-book sportsbook registry scraped directly via intelligent "
            "fallback — more sources than any other odds service, with no paid "
            "odds API. "
            "Use to get the complete multi-source picture for a single event, "
            "e.g. call with event_id='nba:bda33adc...' and sources='all' to "
            "compare every book and feed on one matchup; the merged result is "
            "deduped with the sharpest line winning conflicts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": (
                        "Event id to aggregate; accepts an optional 'sport:event_id' "
                        "prefix, e.g. 'nba:bda33adc...' (use get_odds to list ids)"
                    ),
                },
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h', 'spreads', 'totals', or a "
                        "comma/pipe separated combo); default is h2h moneyline"
                    ),
                },
                "book": {
                    "type": "string",
                    "description": (
                        "Optional single-book filter (e.g., 'draftkings'); omit "
                        "for every reachable source"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of merged odds records (default: 50)",
                },
                "sources": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Comma-separated source list: the_odds_api, espn, "
                        "oddsportal, bovada, betonline, or 'all' (default) for "
                        "every reachable source"
                    ),
                },
            },
            "required": ["event_id"],
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
                            "event": {"type": "string"},
                            "market": {"type": "string"},
                            "book": {"type": "string"},
                            "source": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
                        },
                    },
                },
                "event_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]
