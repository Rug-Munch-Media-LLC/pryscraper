"""Pry - MCP tool definitions: deals / drop-alert tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher, _new_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_deals",
        "description": (
            "Search deals, discounts, and promotions by keyword across public deal feeds, "
            "returning merchant, product, price, discount percentage, and expiry for each "
            "result. "
            "Use to build deal trackers, power shopping comparisons, or feed coupon "
            "content, e.g. query='PS5' for current console offers. Best-effort over free "
            "public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Deal search keywords, e.g. 'PS5'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of deals to return (default: 20)",
                },
            },
            "required": ["query"],
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
                                    "title": {"type": "string"},
                                    "merchant": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "discount_pct": {"type": "number"},
                                    "expires_at": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_drop_alert",
        "description": (
            "Check for drop alerts / limited product restock or flash-sale signals for a "
            "product, returning availability windows, price drops, and the merchant for "
            "each signal, e.g. product='RTX 5090' to track GPU drops. "
            "Use to power restock-notification bots, supply monitoring, or scalper-"
            "resistant buying queues. Best-effort over public feeds; degrades to an "
            "empty list when no drop signal is found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Product name or SKU to watch for drops, e.g. 'RTX 5090'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of drop signals to return (default: 20)",
                },
            },
            "required": ["product"],
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
                                    "product": {"type": "string"},
                                    "merchant": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "availability": {"type": "string"},
                                    "alert_type": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "product": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

_DEALS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_deals": (
        ("coupons", ("search_deals", "get_deals", "deals_search", "find_deals")),
        ("drops", ("search_deals", "get_deals", "deals_search")),
    ),
    "pry_drop_alert": (
        (
            "drops",
            ("check_drop_alerts", "list_alerts", "get_drop_alerts", "drop_alerts"),
        ),
    ),
}


async def call_deals_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch deals MCP tools to their ``deals_data`` handlers (guarded).

    The ``deals_data`` subpackage (``deals``, ``drops``) is built in parallel
    by other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-deals tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "deals_data",
        _DEALS_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_deals": "query", "pry_drop_alert": "product"},
    )
