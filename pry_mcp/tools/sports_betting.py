"""Pry - MCP tool definitions: sports-betting tools (odds, lines, props).

Split from the former ``pry_mcp/tools/sports.py`` god file. Holds the
betting-domain tool schemas (``PRY_TOOLS``) and the guarded candidate
registry (``_SPORTS_TOOL_FNS``) for odds / arbitrage / +EV / props /
live-odds plus the expanded sportsbook coverage (books, book coverage,
scrape methods, all-sources odds aggregator).
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
        "name": "pry_odds",
        "description": (
            "Get live betting odds across major bookmakers (DraftKings, FanDuel, "
            "BetMGM, ESPN BET, ...) for one or more sports, backed by The Odds API "
            "(free tier via PRY_ODDS_API_KEY) with an ESPN scoreboard fallback. "
            "Each record includes the event label, market, bookmaker, and decimal "
            "odds for home/away. "
            "Use to compare lines before placing a bet or to power an odds "
            "aggregator, e.g. 'what are the current NBA moneyline odds across "
            "books?' or call with sport='nfl' to see the full NFL slate."
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
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h' moneyline, 'spreads', "
                        "'totals'); the default feed is h2h moneyline"
                    ),
                },
                "book": {
                    "type": "string",
                    "description": (
                        "Bookmaker name filter (e.g., 'DraftKings', 'FanDuel', "
                        "'BetMGM'); omit for every book"
                    ),
                },
                "event_query": {
                    "type": "string",
                    "description": "Substring filter on event label, e.g. 'celtics'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of odds records (default: 20)",
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
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
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
    {
        "name": "pry_arbitrage",
        "description": (
            "Scan sportsbook lines for guaranteed-profit arbitrage opportunities: "
            "the same event quoted at different books where the combined implied "
            "probabilities total under 100%. "
            "Use to find risk-free bets, e.g. 'show me NFL arbitrage opportunities "
            "with at least 0.8% yield' or call with sport='all' to sweep every "
            "tracked league."
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
                "min_yield_pct": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0,
                    "maximum": 100,
                    "description": ("Minimum guaranteed yield in percent to report (default: 0.5)"),
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
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "market": {"type": "string"},
                            "books": {"type": "object"},
                            "total_implied": {"type": "number"},
                            "arb_yield_pct": {"type": "number"},
                            "stake_split": {"type": "object"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "min_yield_pct": {"type": "number"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_plus_ev",
        "description": (
            "Find positive expected-value (+EV) betting opportunities by comparing "
            "market odds against a sharp book's line or consensus price. "
            "Use to identify bets where the market price is better than the fair "
            "probability implies, e.g. 'what are the best +EV bets right now?' or "
            "call with sharp_book='pinnacle' and min_ev_pct=2.0 to only see edges "
            "above 2%."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sharp_book": {
                    "type": "string",
                    "default": "pinnacle",
                    "description": (
                        "Sharp book to treat as the fair line reference "
                        "(e.g., 'pinnacle', 'circa', 'betonline')"
                    ),
                },
                "min_ev_pct": {
                    "type": "number",
                    "default": 1.0,
                    "minimum": 0,
                    "maximum": 100,
                    "description": ("Minimum expected value in percent to report (default: 1.0)"),
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
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "market": {"type": "string"},
                            "side": {"type": "string"},
                            "book": {"type": "string"},
                            "odds": {"type": "number"},
                            "fair_prob": {"type": "number"},
                            "implied_prob": {"type": "number"},
                            "ev_pct": {"type": "number"},
                        },
                    },
                },
                "sharp_book": {"type": "string"},
                "min_ev_pct": {"type": "number"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_props",
        "description": (
            "Get player prop betting lines (points, rebounds, assists, yards, "
            "strikeouts, ...) for a player or sport, with the market and book "
            "prices. "
            "Use to research player props before betting or building a props "
            "dashboard, e.g. 'what are LeBron James points props tonight?' or call "
            "with sport='nfl' and market='passing_yards' to see QB yardage props."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player": {
                    "type": "string",
                    "description": "Player name, e.g. 'LeBron James'",
                },
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "market": {
                    "type": "string",
                    "description": (
                        "Prop market (e.g., 'points', 'rebounds', 'passing_yards', "
                        "'strikeouts'); omit for every market"
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
                            "event": {"type": "string"},
                            "player": {"type": "string"},
                            "sport": {"type": "string"},
                            "market": {"type": "string"},
                            "line": {"type": "number"},
                            "bookmaker": {"type": "string"},
                            "over_odds": {"type": "number"},
                            "under_odds": {"type": "number"},
                        },
                    },
                },
                "player": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_live_odds",
        "description": (
            "Get live in-play odds that update during games (moneyline, spreads, "
            "totals as they move). "
            "Use for live-betting research or game-flow monitoring, e.g. 'what are "
            "the live odds for the Lakers game right now?' or call with sport='nba' "
            "and limit=50 for the current in-play slate."
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
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of live odds records (default: 20)",
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
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
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

# ── Sports-betting candidate registry (guarded) ───────────────────────
# Candidate public function names for the sports_data betting modules. The
# odds / arbitrage / ev / props modules have already landed (get_odds,
# find_arbitrage, find_plus_ev, get_player_props); live_odds lands from
# parallel agents. Each tool maps to one or more (module, candidate-callables)
# options tried in order, so the dispatcher resolves whichever module/function
# the landed code actually exposes.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_odds": (("odds", ("get_odds",)),),
    "pry_arbitrage": (("arbitrage", ("get_arbitrage", "find_arbitrage", "scan_arbitrage")),),
    "pry_plus_ev": (
        ("ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
        ("plus_ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
    ),
    "pry_props": (("props", ("get_player_props", "get_props", "search_props", "player_props")),),
    "pry_live_odds": (
        ("live", ("get_live_odds", "live_odds")),
        ("live_odds", ("get_live_odds", "live_odds")),
    ),
    # Expanded sportsbook coverage (landed from parallel agents): the 112-book
    # registry scraper (books.py) and the multi-source odds aggregator (odds.py).
    # books.get_all_books_odds is async; books.books_coverage is sync (the
    # dispatcher below handles both). pry_scrape_methods reads the
    # scraping_methods.METHODS registry (fallback-chain tiers) and is
    # special-cased in call_sports_tool.
    "pry_books": (("books", ("get_all_books_odds",)),),
    "pry_book_coverage": (("books", ("books_coverage",)),),
    "pry_scrape_methods": (("scraping_methods", ("METHODS",)),),
    "pry_all_sources": (("odds", ("get_odds_multi",)),),
}
