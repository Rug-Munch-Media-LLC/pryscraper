"""Pry - MCP tool definitions: KOL / social leaderboards tools.

Split from the former ``pry_mcp/tools/crypto.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from .crypto_common import _crypto_module_unavailable, _json_result

logger = logging.getLogger(__name__)

PRY_KOL_TOOLS: list[dict[str, Any]] = [
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
]


async def handle_kol_leaderboards(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_kol_leaderboards`` to its ``crypto_market`` handler."""
    source = arguments.get("source", "kolscan_leaderboard")
    limit = int(arguments.get("limit", 500))
    health_only = bool(arguments.get("health_only", False))
    try:
        from crypto_market.kol_leaderboards import fetch_kol_leaderboards
    except ImportError as e:
        logger.warning(
            "suppressed %s in handle_kol_leaderboards (crypto_social.py:108): %s",
            "ImportError",
            e,
        )
        return _crypto_module_unavailable(name)
    if health_only:
        try:
            from crypto_market.kol_leaderboards import source_health
        except ImportError as e:
            logger.warning(
                "suppressed %s in handle_kol_leaderboards (crypto_social.py:113): %s",
                "ImportError",
                e,
            )
            return _crypto_module_unavailable(name)
        return _json_result(source_health())
    sources = None if source == "all" else [source]
    result = await fetch_kol_leaderboards(limit=limit, sources=sources)
    return _json_result(result)
