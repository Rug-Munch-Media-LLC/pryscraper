"""Pry - MCP tool definitions: real-estate tools and dispatcher..

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

from ._common import _data_module_unavailable, _missing_arg

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_realestate_search",
        "description": (
            "Search real-estate listings by location and status (for_sale, for_rent, sold), "
            "returning address, price, beds/baths, square footage, and listing URLs. "
            "Use for market research, comps, or lead generation, e.g. 'what's for sale in "
            "Austin, TX under $500k?'. Scrapes Zillow search pages with a Redfin GIS API "
            "fallback (both free and keyless); never raises and returns an empty list when "
            "the source is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or neighborhood, e.g. 'Austin, TX'",
                },
                "status": {
                    "type": "string",
                    "enum": ["for_sale", "for_rent", "sold"],
                    "default": "for_sale",
                    "description": "Listing status filter (default: for_sale)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum number of listings to return (default: 20)",
                },
            },
            "required": ["location"],
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
                            "zpid": {"type": "string"},
                            "address": {"type": "string"},
                            "price": {"type": "number"},
                            "beds": {"type": "integer"},
                            "baths": {"type": "number"},
                            "sqft": {"type": "integer"},
                            "status": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "location": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    }
]


async def call_realestate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch real-estate MCP tools to their ``real_estate`` handlers (guarded)."""
    if name == "pry_realestate_search":
        location = arguments.get("location", "")
        if not location:
            return _missing_arg(name, "location")
        status = arguments.get("status", "for_sale")
        limit = int(arguments.get("limit", 20))
        try:
            from real_estate.listings import search_listings
        except ImportError:
            return _data_module_unavailable(name, "real_estate")
        data = await search_listings(location, status=status, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "location": location, "status": status},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None
