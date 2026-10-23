"""Pry - MCP tool definitions: token launch and CX listing tools.

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

PRY_LAUNCH_TOOLS: list[dict[str, Any]] = [
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
                    "type": "array",
                    "description": (
                        "New or trending tokens; empty when every upstream source "
                        "fails."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "chain": {"type": "string"},
                            "address": {"type": "string"},
                            "symbol": {"type": "string"},
                            "name": {"type": "string"},
                            "pair_address": {"type": "string"},
                            "created_at_utc": {"type": "string"},
                            "created_at": {"type": "string"},
                            "price_usd": {"type": "number"},
                            "liquidity_usd": {"type": "number"},
                            "volume_24h_usd": {"type": "number"},
                            "price_change_24h_pct": {"type": "number"},
                            "source": {"type": "string"},
                        },
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


async def handle_token_launches(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_token_launches`` to its ``crypto_market`` handler."""
    kind = arguments.get("kind", "tokens")
    chain = arguments.get("chain", "all")
    limit = int(arguments.get("limit", 50))
    try:
        from datasets.crypto_market.token_launches import (
            get_new_pairs,
            get_new_tokens,
            get_trending_tokens,
        )
    except ImportError as e:
        logger.warning(
            "suppressed %s in handle_token_launches (crypto_launches.py:165): %s",
            "ImportError",
            e,
        )
        return _crypto_module_unavailable(name)
    fn = {
        "tokens": get_new_tokens,
        "pairs": get_new_pairs,
        "trending": get_trending_tokens,
    }.get(kind, get_new_tokens)
    launches_data = await fn(chain=chain, limit=limit)
    return _json_result(launches_data)


async def handle_cex_listings(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_cex_listings`` to its ``crypto_market`` handler."""
    exchanges = arguments.get("exchanges") or None
    lookback_hours = int(arguments.get("lookback_hours", 24))
    try:
        from datasets.crypto_market.cex_listings import get_listing_signals
    except ImportError as e:
        logger.warning(
            "suppressed %s in handle_cex_listings (crypto_launches.py:182): %s",
            "ImportError",
            e,
        )
        return _crypto_module_unavailable(name)
    signals_data = await get_listing_signals(exchanges=exchanges, lookback_hours=lookback_hours)
    return _json_result(signals_data)
