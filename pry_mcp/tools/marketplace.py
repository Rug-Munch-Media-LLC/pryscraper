"""Pry - MCP tool definitions: marketplace tools and the ``call_marketplace_tool`` dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from typing import Any

from ._common import _missing_arg

logger = logging.getLogger(__name__)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_amazon_product",
        "description": (
            "Look up a single Amazon product by its ASIN (e.g. 'B08N5WRWNW') and return "
            "current price, title, rating, and listing details from the "
            "marketplace intelligence provider. "
            "Use to check a product's live price or stock, e.g. 'what does B0BLVMHNF1 "
            "cost right now?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "asin": {
                    "type": "string",
                    "description": (
                        "Amazon Standard Identification Number (10-character "
                        "alphanumeric), e.g. 'B08N5WRWNW'"
                    ),
                },
            },
            "required": ["asin"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "description": (
                        "One normalized Amazon product; an empty object when the "
                        "listing could not be read."
                    ),
                    "properties": {
                        "asin": {"type": "string"},
                        "title": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "buy_box": {"type": "string"},
                        "brand": {"type": "string"},
                        "rating": {"type": "number"},
                        "review_count": {"type": "integer"},
                        "bsr": {"type": "integer"},
                        "category": {"type": "string"},
                        "offers": {"type": "integer"},
                        "url": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_amazon_search",
        "description": (
            "Search Amazon products by keyword and return matching listings — title, "
            "price, rating, and ASIN for each result (up to limit). "
            "Use to compare prices or discover products, e.g. 'search Amazon for "
            "wireless mechanical keyboards'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords, e.g. 'wireless mechanical keyboard'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of results to return (default: 20)",
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
                    "description": (
                        "Matching products in scrape order; empty when Amazon blocks "
                        "the search or nothing matches."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "asin": {"type": "string"},
                            "title": {"type": "string"},
                            "price": {"type": "number"},
                            "currency": {"type": "string"},
                            "buy_box": {"type": "string"},
                            "brand": {"type": "string"},
                            "rating": {"type": "number"},
                            "review_count": {"type": "integer"},
                            "bsr": {"type": "integer"},
                            "category": {"type": "string"},
                            "offers": {"type": "integer"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_walmart_product",
        "description": (
            "Look up a single Walmart product by its product ID (e.g. '4JH7P89H7X5P') "
            "and return current price, title, stock, seller, and rating from the "
            "marketplace intelligence provider. "
            "Use to check a Walmart listing's live price or stock, e.g. 'what does "
            "Walmart product 4JH7P89H7X5P cost?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": ("Walmart product ID (alphanumeric), e.g. '4JH7P89H7X5P'"),
                },
            },
            "required": ["product_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "description": (
                        "One normalized Walmart product; an empty object when the "
                        "listing could not be read."
                    ),
                    "properties": {
                        "product_id": {"type": "string"},
                        "title": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "seller": {"type": "string"},
                        "rating": {"type": "number"},
                        "stock": {"type": "boolean"},
                        "url": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_tiktok_trending",
        "description": (
            "Get currently trending products on TikTok Shop, ranked by engagement and "
            "sales velocity, with price, sales count, and shop info for each result "
            "(up to limit). "
            "Use to spot viral commerce opportunities, e.g. 'what's trending on TikTok "
            "Shop right now?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of trending items to return (default: 50)",
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
                        "Trending products in engagement order; empty when the "
                        "bestseller surface is unavailable."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "title": {"type": "string"},
                            "price": {"type": "number"},
                            "sold_count": {"type": "integer"},
                            "gmv_estimate": {"type": "number"},
                            "rating": {"type": "number"},
                            "shop": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]


def _marketplace_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a marketplace tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the marketplace module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


async def call_marketplace_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the marketplace-intelligence MCP tools to their handlers.

    The ``marketplace`` subpackage (``amazon``, ``walmart``, ``tiktok_shop``)
    is built in parallel by other agents; every import is guarded so this
    dispatcher degrades gracefully (a readable message) if a module has not
    landed yet. Returns ``None`` for non-marketplace tools so callers fall
    through to their normal execution path (remote executor / REST proxy).
    """
    if name == "pry_amazon_product":
        asin = arguments.get("asin", "")
        if not asin:
            return _missing_arg(name, "asin")
        try:
            from pry.commerce.marketplace.amazon import get_product as get_amazon_product
        except ImportError as e:
            logger.warning(
                "suppressed %s in call_marketplace_tool (marketplace.py:251): %s",
                "ImportError",
                e,
            )
            return _marketplace_module_unavailable(name)
        product_data = await get_amazon_product(asin)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": product_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_amazon_search":
        query = arguments.get("query", "")
        if not query:
            return _missing_arg(name, "query")
        limit = int(arguments.get("limit", 20))
        try:
            from pry.commerce.marketplace.amazon import search_products as search_amazon_products
        except ImportError as e:
            logger.warning(
                "suppressed %s in call_marketplace_tool (marketplace.py:271): %s",
                "ImportError",
                e,
            )
            return _marketplace_module_unavailable(name)
        search_data = await search_amazon_products(query, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": search_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_walmart_product":
        product_id = arguments.get("product_id", "")
        if not product_id:
            return _missing_arg(name, "product_id")
        try:
            from pry.commerce.marketplace.walmart import get_product as get_walmart_product
        except ImportError as e:
            logger.warning(
                "suppressed %s in call_marketplace_tool (marketplace.py:290): %s",
                "ImportError",
                e,
            )
            return _marketplace_module_unavailable(name)
        product_data = await get_walmart_product(product_id)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": product_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_tiktok_trending":
        limit = int(arguments.get("limit", 50))
        try:
            from pry.commerce.marketplace.tiktok_shop import get_trending
        except ImportError as e:
            logger.warning(
                "suppressed %s in call_marketplace_tool (marketplace.py:307): %s",
                "ImportError",
                e,
            )
            return _marketplace_module_unavailable(name)
        trending_data = await get_trending(limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": trending_data}, indent=2),
                }
            ],
            "isError": False,
        }

    return None
