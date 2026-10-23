"""Pry - MCP tool definitions: sportsbook coverage / consensus / alerts tool definitions..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
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
        "name": "pry_historical_odds",
        "description": (
            "Get historical betting odds for past events from The Odds API "
            "history feed: the closing lines, opening lines, and best available "
            "prices for moneyline, spreads, and totals on a given date. "
            "Use to backtest betting models or audit how lines moved, e.g. "
            "'what were the closing NFL moneylines on 20260810?' or call with "
            "sport='nba' and date='2026-08-01' for that day's historical slate."
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
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of historical records (default: 20)",
                },
                "event_id": {
                    "type": "string",
                    "description": (
                        "Odds API event id the history feed is queried for, "
                        "e.g. 'nba:bda33adc' (from pry_odds / pry_all_sources)"
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
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "date": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_betting_percentages",
        "description": (
            "Get public betting percentages (the share of bets and the share of "
            "money on each side of a game) across bookmakers, e.g. 'how much of "
            "the money is on the Chiefs tonight?' or call with sport='nfl' to see "
            "the whole slate. Use to spot sharp-side steam and contrarian plays "
            "where the public leans one way but the line is not moving."
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
                "event": {
                    "type": "string",
                    "description": (
                        "Event id the handler keys on, e.g. 'nba:bda33adc' (from pry_live_games)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of percentage records (default: 20)",
                },
            },
            "required": ["event"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "description": (
                        "Betting-percentage record for the requested event; an "
                        "empty object when none is published"
                    ),
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_alerts",
        "description": (
            "Get or manage money-printer alerts: significant line moves, sharp "
            "steam, limit-up CLV, and bettor-facing notifications you subscribe "
            "to. Use to stay on top of the market without polling, e.g. 'what "
            "alerts are active right now?' or call with alert_type='line_move' "
            "to list the biggest recent line moves across all sports."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "alert_type": {
                    "type": "string",
                    "default": "",
                    "description": (
                        "Alert category filter: 'line_move', 'steam', 'clv', "
                        "'injury', or empty for all"
                    ),
                },
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of alerts (default: 20)",
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
                            "alert_type": {"type": "string"},
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "message": {"type": "string"},
                            "severity": {"type": "string"},
                            "created_at": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_books",
        "description": (
            "Aggregate live odds for one sport/market across all 112 sportsbooks "
            "in Pry's registry (US, offshore, EU, UK, and Asian books) by "
            "scraping each book directly through Pry's intelligent fallback "
            "chain — no paid odds API, no API keys. "
            "Use to find the best price anywhere for a slate, e.g. call with "
            "sport='nba' and market='h2h' to see every reachable book's "
            "moneyline for tonight's games, or pass market='spreads' to sweep "
            "the point-spread market across the whole registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport key to aggregate (e.g. 'nba', 'nfl', 'mlb', 'nhl', "
                        "'epl'); books are scraped per-sport (default: nba)"
                    ),
                },
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h' moneyline, 'spreads', "
                        "'totals'); default is h2h moneyline"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of odds records to return (default: 50)",
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
                            "event": {"type": "string"},
                            "market": {"type": "string"},
                            "book": {"type": "string"},
                            "book_id": {"type": "string"},
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "market": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_book_coverage",
        "description": (
            "Get sportsbook coverage-registry statistics: how many of the 112 "
            "sportsbooks Pry scrapes directly, broken down by category (US, "
            "offshore, EU, UK, Asian), extraction method, and geo-requirement. "
            "Use to verify the breadth of the no-paid-API odds network before "
            "relying on it, e.g. 'how many US books do you cover?' or to confirm "
            "the 112-book total and the per-category split in one call."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "total": {"type": "integer"},
                        "by_category": {"type": "object"},
                        "by_method": {"type": "object"},
                        "geo_required": {"type": "object"},
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "methods": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
]
