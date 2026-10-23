"""Pry - MCP tool definitions: food data tools (grocery, restaurant).

Split from the former ``pry_mcp/tools/data.py`` god file. Holds the
food-domain tool schemas (``PRY_TOOLS``), the guarded candidate registry
(``_FOOD_TOOL_FNS``), and the ``call_food_tool`` dispatcher.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_data import _broad_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_grocery",
        "description": (
            "Get grocery prices for a product or category, optionally filtered "
            "by ZIP code for local store pricing. Use to compare staple costs "
            "across markets, e.g. 'price of a dozen eggs in 10001', or call "
            "with query='milk' and zip='78701' to see regional averages and "
            "store-level ranges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Item or category, e.g. 'eggs', 'milk', 'avocados'",
                },
                "zip": {
                    "type": "string",
                    "description": "5-digit ZIP code for local pricing (optional)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of price records (default: 20)",
                },
            },
            "required": ["query"],
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
                            "item": {"type": "string"},
                            "price_usd": {"type": "number"},
                            "unit": {"type": "string"},
                            "store": {"type": "string"},
                            "zip": {"type": "string"},
                            "date": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_restaurant",
        "description": (
            "Get a restaurant's menu with prices: items, sections, and per-dish "
            "pricing for a named restaurant. Use to build cost-of-dining "
            "datasets or research competitors, e.g. call with "
            "name=\"Katz's Delicatessen\" and location='New York' for the full "
            "menu with prices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": 'Restaurant name, e.g. "Katz\'s Delicatessen"',
                },
                "location": {
                    "type": "string",
                    "description": "City / address to disambiguate (optional)",
                },
            },
            "required": ["name"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "cuisine": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "section": {"type": "string"},
                                    "items": {"type": "array", "items": {"type": "object"}},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Food candidate registry (guarded) ─────────────────────────────────
# Candidate public function names for the food_data package (``grocery``,
# ``restaurants``). These land from parallel agents; every import is guarded
# so the dispatcher degrades gracefully (a readable message) if a module has
# not landed yet.
_FOOD_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_grocery": (("grocery", ("get_grocery_prices", "grocery_prices", "get_prices")),),
    "pry_restaurant": (("restaurants", ("get_restaurant_menu", "restaurant_menu", "get_menu")),),
}


async def call_food_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch food-data MCP tools to their ``food_data`` handlers (guarded).

    The ``food_data`` subpackage (``grocery``, ``restaurants``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-food tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "food_data",
        _FOOD_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_grocery": "query", "pry_restaurant": "name"},
    )
