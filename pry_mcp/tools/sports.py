"""Pry - MCP tool definitions: sports-betting odds tools and the ``call_sports_tool`` dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import Any

from ._common import _callable_accepts

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
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "yield_pct": {"type": "number"},
                            "legs": {"type": "array", "items": {"type": "object"}},
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
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "ev_pct": {"type": "number"},
                            "sharp_book": {"type": "string"},
                            "best_book": {"type": "string"},
                            "price": {"type": "number"},
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
                            "player": {"type": "string"},
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "line": {"type": "number"},
                            "over_price": {"type": "number"},
                            "under_price": {"type": "number"},
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

# ── Sports-betting domain (parallel build, guarded) ────────────────────
# Candidate public function names for the sports_data modules. The odds /
# scores / arbitrage / ev / props modules have already landed (get_odds,
# get_scores, find_arbitrage, find_plus_ev, get_player_props); injuries and
# live_odds land from parallel agents. Each tool maps to one or more
# (module, candidate-callables) options tried in order, so the dispatcher
# resolves whichever module/function the landed code actually exposes.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_odds": (("odds", ("get_odds",)),),
    "pry_scores": (("scores", ("get_scores",)),),
    "pry_arbitrage": (("arbitrage", ("get_arbitrage", "find_arbitrage", "scan_arbitrage")),),
    "pry_plus_ev": (
        ("ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
        ("plus_ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
    ),
    "pry_props": (("props", ("get_player_props", "get_props", "search_props", "player_props")),),
    "pry_injuries": (("injuries", ("get_injuries", "list_injuries", "injury_report")),),
    "pry_live_odds": (
        ("live", ("get_live_odds", "live_odds")),
        ("live_odds", ("get_live_odds", "live_odds")),
    ),
    # Money-printer tools land from parallel agents (historical_odds,
    # betting_percentages, sharp_consensus, alerts). Each maps to one or more
    # (module, candidate-callables) options so the landed module/function name
    # is resolved defensively, mirroring the arbitrage/plus_ev pattern.
    "pry_historical_odds": (
        ("historical", ("get_historical_odds", "historical_odds", "get_historical")),
        ("historical_odds", ("get_historical_odds", "historical_odds", "get_historical")),
    ),
    "pry_betting_percentages": (
        (
            "betting_percentages",
            ("get_betting_percentages", "betting_percentages", "get_percentages"),
        ),
        ("percentages", ("get_betting_percentages", "betting_percentages", "get_percentages")),
    ),
    "pry_sharp_consensus": (
        ("sharp_consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
        ("consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
    ),
    "pry_alerts": (
        ("alerts", ("list_alerts", "get_alerts", "alerts")),
        ("alert", ("list_alerts", "get_alerts", "alerts")),
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


def _sports_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a sports tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the sports_data module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _sports_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for a sports tool from MCP arguments.

    The declared schema (sport/market/book/... ) is richer than what some
    landed modules accept today; kwargs the callable does not support are
    filtered out by the dispatcher (``_callable_accepts``) so the call never
    fails on an unknown keyword.
    """
    if name == "pry_odds":
        kwargs = {
            "event_query": arguments.get("event_query", ""),
            "sport": arguments.get("sport", "all"),
            "limit": int(arguments.get("limit", 20)),
        }
        # Only forward market/book when the caller actually set them — the
        # landed get_odds defaults (market="h2h", book=None) are safer than
        # empty strings (book="" would normalize to "unknown").
        if arguments.get("market"):
            kwargs["market"] = arguments["market"]
        if arguments.get("book"):
            kwargs["book"] = arguments["book"]
        return kwargs
    if name == "pry_scores":
        return {"sport": arguments.get("sport", "all"), "date": arguments.get("date", "today")}
    if name == "pry_arbitrage":
        return {
            "sport": arguments.get("sport", "all"),
            "min_yield_pct": float(arguments.get("min_yield_pct", 0.5)),
        }
    if name == "pry_plus_ev":
        return {
            "sharp_book": arguments.get("sharp_book", "pinnacle"),
            "min_ev_pct": float(arguments.get("min_ev_pct", 1.0)),
        }
    if name == "pry_props":
        return {
            "player": arguments.get("player", ""),
            "sport": arguments.get("sport", "all"),
            "market": arguments.get("market", ""),
        }
    if name == "pry_injuries":
        return {"sport": arguments.get("sport", "all"), "team": arguments.get("team", "all")}
    if name == "pry_live_odds":
        return {"sport": arguments.get("sport", "all"), "limit": int(arguments.get("limit", 20))}
    if name == "pry_historical_odds":
        kwargs = {
            "sport": arguments.get("sport", "all"),
            "date": arguments.get("date", "today"),
            "limit": int(arguments.get("limit", 20)),
        }
        # The landed historical module keys off the Odds API event id.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        elif arguments.get("event_query"):
            kwargs["event_id"] = arguments["event_query"]
        return kwargs
    if name == "pry_betting_percentages":
        kwargs = {"sport": arguments.get("sport", "all")}
        # The landed percentages module is event-id centric.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        elif arguments.get("event"):
            kwargs["event_id"] = arguments["event"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_sharp_consensus":
        kwargs = {"sport": arguments.get("sport", "all")}
        # The landed consensus module is event-id centric.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        if arguments.get("sharp_books"):
            kwargs["books"] = arguments["sharp_books"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_alerts":
        kwargs = {"sport": arguments.get("sport", "all")}
        if arguments.get("alert_type"):
            kwargs["alert_type"] = arguments["alert_type"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_books":
        kwargs = {
            "sport": arguments.get("sport", "nba"),
            "market": arguments.get("market", "h2h"),
            "limit": int(arguments.get("limit", 50)),
        }
        return kwargs
    if name == "pry_book_coverage":
        return {}
    if name == "pry_scrape_methods":
        return {}
    if name == "pry_all_sources":
        kwargs = {
            "event_id": arguments.get("event_id", ""),
            "market": arguments.get("market", "h2h"),
            "limit": int(arguments.get("limit", 50)),
            "sources": arguments.get("sources", "all"),
        }
        if arguments.get("book"):
            kwargs["book"] = arguments["book"]
        return kwargs
    return dict(arguments)


async def call_sports_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch sports-betting MCP tools to their ``sports_data`` handlers (guarded).

    The ``sports_data`` subpackage (odds, scores, arbitrage, plus_ev, props,
    injuries, live_odds, books) is built in parallel by other agents; every
    import is guarded so this dispatcher degrades gracefully (a readable
    message) if a module has not landed yet. Returns ``None`` for non-sports
    tools so callers fall through to their normal execution path (remote
    executor / REST proxy).
    """
    entry = _SPORTS_TOOL_FNS.get(name)
    if entry is None:
        return None
    # pry_scrape_methods reads the METHODS registries (dicts/tuples of method
    # metadata, not callables) — resolve them directly instead of trying to
    # call them. Primary source is the top-level scraping_methods module
    # (fallback-chain tiers); the sports_data.books extraction vocabulary is
    # the fallback.
    if name == "pry_scrape_methods":
        try:
            mod = __import__("scraping_methods", fromlist=["METHODS"])
            registry = getattr(mod, "METHODS", {})
            if isinstance(registry, dict):
                methods = [
                    {
                        "key": key,
                        "name": str(meta.get("name", key)),
                        "sync": bool(meta.get("sync", False)),
                        "cost": str(meta.get("cost", "")),
                        "when": str(meta.get("when", "")),
                        "notes": str(meta.get("notes", "")),
                    }
                    for key, meta in registry.items()
                ]
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "success": True,
                                    "data": {"methods": methods, "total": len(methods)},
                                },
                                indent=2,
                            ),
                        }
                    ],
                    "isError": False,
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "success": True,
                                "data": {"methods": list(registry), "total": len(registry)},
                            },
                            indent=2,
                        ),
                    }
                ],
                "isError": False,
            }
        except ImportError:
            pass
        try:
            mod = __import__("sports_data.books", fromlist=["books"])
        except ImportError:
            return _sports_module_unavailable(name)
        book_methods: tuple[str, ...] = getattr(mod, "METHODS", ())
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "data": {"methods": list(book_methods), "total": len(book_methods)},
                        },
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }
    for module_name, candidates in entry:
        try:
            mod = __import__(f"sports_data.{module_name}", fromlist=[module_name])
        except ImportError:
            continue
        fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
        if fn is None:
            continue
        kwargs = _sports_tool_kwargs(name, arguments)
        result = fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        # Handlers are usually async (get_all_books_odds, get_odds_multi) but
        # some are sync registry reads (books_coverage) — await only when the
        # callable actually returned a coroutine.
        import inspect

        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": data}, indent=2),
                }
            ],
            "isError": False,
        }
    return _sports_module_unavailable(name)
