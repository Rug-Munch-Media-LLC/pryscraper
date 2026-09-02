"""Pry - MCP tool definitions: attention / SEO tools and dispatcher..

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
        "name": "pry_serp",
        "description": (
            "Scrape a Google search results page for a query, returning organic results, "
            "the AI Overview text when present, and People Also Ask questions. Use for SEO "
            "rank tracking or competitor SERP analysis, e.g. 'who ranks for best wireless "
            "keyboard?'. Built on the free public Google results page; never raises and "
            "returns an error payload when Google serves a consent or CAPTCHA wall."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query, e.g. 'best wireless keyboard'",
                },
                "num": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum organic results to parse (default: 10)",
                },
            },
            "required": ["q"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "organic": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rank": {"type": "integer"},
                                    "title": {"type": "string"},
                                    "url": {"type": "string"},
                                    "snippet": {"type": "string"},
                                },
                            },
                        },
                        "ai_overview": {"type": "string"},
                        "people_also_ask": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_trends",
        "description": (
            "Measure Google Trends interest over time for a keyword, returning the daily "
            "interest timeline and related queries. Use to validate demand for a product, "
            "content topic, or token narrative before committing resources, e.g. 'is AI "
            "agents interest rising?'. Built on the free Trends public endpoint; never "
            "raises and returns an error payload when the endpoint is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Keyword to measure, e.g. 'AI agents'",
                },
                "timeframe": {
                    "type": "string",
                    "default": "today 12-m",
                    "description": "Trends timeframe, e.g. 'today 12-m', 'today 3-m', 'now 7-d'",
                },
            },
            "required": ["keyword"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "timeline": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "interest": {"type": "number"},
                                },
                            },
                        },
                        "related_queries": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
]


async def call_attention_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch attention/SEO MCP tools to their ``attention`` handlers (guarded)."""
    if name == "pry_serp":
        q = arguments.get("q", "")
        if not q:
            return _missing_arg(name, "q")
        num = int(arguments.get("num", 10))
        try:
            from attention.serp import serp
        except ImportError:
            return _data_module_unavailable(name, "attention")
        data = await serp(q, num=num)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": "error" not in data, "data": data, "query": q}, indent=2
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_trends":
        keyword = arguments.get("keyword", "")
        if not keyword:
            return _missing_arg(name, "keyword")
        timeframe = arguments.get("timeframe", "today 12-m")
        try:
            from attention.trends import trend_interest
        except ImportError:
            return _data_module_unavailable(name, "attention")
        data = await trend_interest(keyword, timeframe=timeframe)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": "error" not in data, "data": data, "keyword": keyword},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None
