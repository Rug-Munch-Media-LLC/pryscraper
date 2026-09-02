"""Pry - MCP tool definitions: local-business tools and dispatcher..

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
        "name": "pry_places_search",
        "description": (
            "Search Google Maps for local businesses matching a query and location, "
            "returning name, rating, review count, address, and place IDs for lead "
            "generation. Use to build prospect lists for outbound sales, e.g. 'find coffee "
            "shops in Austin TX'. Backed by the free Google Maps public search page; never "
            "raises and returns an empty list when the page is unreachable or blocked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Business type or keyword, e.g. 'taco'",
                },
                "location": {
                    "type": "string",
                    "description": "City or region, e.g. 'Austin TX'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of places to return (default: 20)",
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
                            "place_id": {"type": "string"},
                            "name": {"type": "string"},
                            "rating": {"type": "number"},
                            "reviews_count": {"type": "integer"},
                            "address": {"type": "string"},
                            "phone": {"type": "string"},
                            "website": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_reviews",
        "description": (
            "Get the full review history for a local business place from Google Maps or "
            "Yelp, going beyond the 5-review API cap. Use to analyze customer sentiment, "
            "common complaints, or reputation before outreach, e.g. 'what do customers say "
            "about this restaurant?'. Accepts a Google place CID/slug or a Yelp biz slug; "
            "never raises and returns an empty list when the source is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "place_id": {
                    "type": "string",
                    "description": "Google Maps place CID/slug or Yelp biz slug",
                },
                "source": {
                    "type": "string",
                    "enum": ["google", "yelp"],
                    "default": "google",
                    "description": "Review source (default: google)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of reviews to return (default: 20)",
                },
            },
            "required": ["place_id"],
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
                            "author": {"type": "string"},
                            "rating": {"type": "number"},
                            "date": {"type": "string"},
                            "text": {"type": "string"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "place_id": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]


async def call_local_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch local-business MCP tools to their ``local_data`` handlers (guarded)."""
    if name == "pry_places_search":
        query = arguments.get("query", "")
        if not query:
            return _missing_arg(name, "query")
        location = arguments.get("location", "")
        limit = int(arguments.get("limit", 20))
        try:
            from local_data.places import search_places
        except ImportError:
            return _data_module_unavailable(name, "local_data")
        data = await search_places(query, location=location, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "query": query, "location": location},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_reviews":
        place_id = arguments.get("place_id", "")
        if not place_id:
            return _missing_arg(name, "place_id")
        source = arguments.get("source", "google")
        limit = int(arguments.get("limit", 20))
        try:
            from local_data.reviews import get_reviews
        except ImportError:
            return _data_module_unavailable(name, "local_data")
        data = await get_reviews(place_id, source=source, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "place_id": place_id, "source": source},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None
