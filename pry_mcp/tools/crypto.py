"""Pry - MCP tool definitions: crypto-market tools and the ``call_crypto_tool`` dispatcher..

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

from ._common import _missing_arg

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_kol_leaderboards",
        "description": (
            "Scrape KOL / crypto-influencer leaderboards for usernames (handles), "
            "wallets, followers and P&L / win-loss stats. Reads public trader "
            "leaderboards (kolscan.io Solana trader board; gmgn.ai and dexscreener "
            "smart-money boards are registered but Cloudflare/JS-gated and flagged "
            "[REVIEW]). Use to grow a KOL watchlist, e.g. 'pull the top KOL wallets "
            "from the kolscan leaderboard' or 'find new crypto influencer handles + wallets'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 500,
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum number of KOL records to return (default: 500)",
                },
                "source": {
                    "type": "string",
                    "enum": [
                        "kolscan_leaderboard",
                        "gmgn_smart_money",
                        "dexscreener_smart_money",
                        "all",
                    ],
                    "default": "kolscan_leaderboard",
                    "description": (
                        "Which KOL source to scrape. Blocked sources return a 'blocked' "
                        "annotation (no rows) until a JS-capable solver is wired in."
                    ),
                },
                "health_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, only return per-source reachability/block health.",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "records": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "handle": {"type": "string"},
                                    "name": {"type": "string"},
                                    "address": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "source": {"type": "string"},
                                    "twitter": {"type": "string"},
                                    "profit": {"type": "number"},
                                    "wins": {"type": "integer"},
                                    "losses": {"type": "integer"},
                                    "followers": {"type": "integer"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "blocked": {"type": "array"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_token_launches",
        "description": (
            "Discover new crypto token launches, new liquidity pairs, and trending tokens "
            "across chains (Solana, Ethereum, Base, ...) with optional age filtering. "
            "Use to find early-stage tokens before they hit mainstream trackers, e.g. "
            "'what new Solana tokens launched in the last hour?' or 'show me trending "
            "tokens on Base'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Blockchain filter (e.g., 'solana', 'ethereum', 'base', 'all'). "
                        "Use 'all' to search every supported chain."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of results to return (default: 50)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["tokens", "pairs", "trending"],
                    "default": "tokens",
                    "description": (
                        "What to return: 'tokens' = newly created tokens, "
                        "'pairs' = new liquidity pairs, 'trending' = currently trending tokens"
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
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "address": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "name": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "created_at": {"type": "string"},
                                    "liquidity_usd": {"type": "number"},
                                    "volume_24h_usd": {"type": "number"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "chain": {"type": "string"},
                        "kind": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_cex_listings",
        "description": (
            "Get recent centralized-exchange (CEX) listing and delisting signals — e.g. "
            "Binance, Coinbase, Kraken — aggregated over a configurable lookback window. "
            "Use to time research on tokens that just landed on a major exchange, e.g. "
            "'what did Coinbase list in the last 24 hours?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "exchanges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "CEX names to filter by (e.g., ['binance', 'coinbase', 'kraken']). "
                        "Omit or pass [] to include every tracked exchange."
                    ),
                },
                "lookback_hours": {
                    "type": "integer",
                    "default": 24,
                    "minimum": 1,
                    "maximum": 720,
                    "description": "Look back window in hours (default: 24)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "signals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "token_symbol": {"type": "string"},
                                    "token_address": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "exchange": {"type": "string"},
                                    "event": {"type": "string"},
                                    "announced_at": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "lookback_hours": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

PRY_TOKEN_SECURITY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_token_security",
        "description": (
            "Run a security scan on a crypto token by chain and contract/mint address — "
            "checking for honeypots, hidden mints, ownership concentration, LP lock, and "
            "other rug-pull risk signals. "
            "Use before investing in or reporting on an unfamiliar token, e.g. 'scan "
            "So11111111111111111111111111111111111111112 on solana'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "description": (
                        "Blockchain the token lives on (e.g., 'solana', 'ethereum', 'base')"
                    ),
                },
                "address": {
                    "type": "string",
                    "description": (
                        "Token contract or mint address, e.g. "
                        "'So11111111111111111111111111111111111111112'"
                    ),
                },
            },
            "required": ["chain", "address"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "chain": {"type": "string"},
                        "address": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "risk_level": {"type": "string"},
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    }
]


def _crypto_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a crypto tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the crypto_market module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


async def call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the crypto-market MCP tools to their ``crypto_market`` handlers.

    The ``crypto_market`` subpackage (``token_launches``, ``cex_listings``,
    ``token_security``) is built in parallel by other agents; every import is
    guarded so this dispatcher degrades gracefully (a readable message) if a
    module has not landed yet. Returns ``None`` for non-crypto tools so callers
    fall through to their normal execution path (remote executor / REST proxy).
    """
    if name == "pry_token_launches":
        kind = arguments.get("kind", "tokens")
        chain = arguments.get("chain", "all")
        limit = int(arguments.get("limit", 50))
        try:
            from crypto_market.token_launches import (
                get_new_pairs,
                get_new_tokens,
                get_trending_tokens,
            )
        except ImportError:
            return _crypto_module_unavailable(name)
        fn = {
            "tokens": get_new_tokens,
            "pairs": get_new_pairs,
            "trending": get_trending_tokens,
        }.get(kind, get_new_tokens)
        launches_data = await fn(chain=chain, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": launches_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_cex_listings":
        exchanges = arguments.get("exchanges") or None
        lookback_hours = int(arguments.get("lookback_hours", 24))
        try:
            from crypto_market.cex_listings import get_listing_signals
        except ImportError:
            return _crypto_module_unavailable(name)
        signals_data = await get_listing_signals(exchanges=exchanges, lookback_hours=lookback_hours)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": signals_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_token_security":
        chain = arguments.get("chain", "")
        address = arguments.get("address", "")
        if not chain or not address:
            return _missing_arg(name, "chain and address")
        try:
            from crypto_market.token_security import scan_token
        except ImportError:
            return _crypto_module_unavailable(name)
        scan_data = await scan_token(chain, address)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": scan_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_kol_leaderboards":
        source = arguments.get("source", "kolscan_leaderboard")
        limit = int(arguments.get("limit", 500))
        health_only = bool(arguments.get("health_only", False))
        try:
            from crypto_market.kol_leaderboards import fetch_kol_leaderboards
        except ImportError:
            return _crypto_module_unavailable(name)
        if health_only:
            try:
                from crypto_market.kol_leaderboards import source_health
            except ImportError:
                return _crypto_module_unavailable(name)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"success": True, "data": source_health()}, indent=2),
                    }
                ],
                "isError": False,
            }
        sources = None if source == "all" else [source]
        result = await fetch_kol_leaderboards(limit=limit, sources=sources)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": result}, indent=2),
                }
            ],
            "isError": False,
        }

    return None
