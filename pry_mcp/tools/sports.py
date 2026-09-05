"""Pry - MCP tool definitions: sports-betting odds tools and the ``call_sports_tool`` dispatcher.

Thin re-export module that aggregates the split sports tool modules
(``sports_betting``, ``sports_data``, ``sports_analytics``) and preserves the
former monolithic ``pry_mcp/tools/sports.py`` public API: the merged
``PRY_TOOLS`` registry, the merged ``_SPORTS_TOOL_FNS`` candidate registry,
and the guarded ``call_sports_tool`` dispatcher.
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
from .sports_analytics import _SPORTS_TOOL_FNS as _ANALYTICS_TOOL_FNS, PRY_TOOLS as _ANALYTICS_TOOLS
from .sports_betting import _SPORTS_TOOL_FNS as _BETTING_TOOL_FNS, PRY_TOOLS as _BETTING_TOOLS
from .sports_data import _SPORTS_TOOL_FNS as _DATA_TOOL_FNS, PRY_TOOLS as _DATA_TOOLS

# Merge the per-domain tool lists, preserving the exact tool order of the
# former monolithic sports.py PRY_TOOLS list:
#   odds, arbitrage, plus_ev, props, injuries, live_odds, scores
# (betting holds odds/arbitrage/plus_ev/props/live_odds; data holds
# injuries/scores; analytics currently contributes no schemas).
PRY_TOOLS: list[dict[str, Any]] = [
    *_BETTING_TOOLS[:4],
    *_DATA_TOOLS[:1],
    *_BETTING_TOOLS[4:],
    *_DATA_TOOLS[1:],
    *_ANALYTICS_TOOLS,
]

# Merge the per-domain candidate registries into the single dispatcher
# registry. Dict merge preserves insertion order; the betting entries come
# first, then data, then analytics.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    **_BETTING_TOOL_FNS,
    **_DATA_TOOL_FNS,
    **_ANALYTICS_TOOL_FNS,
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
