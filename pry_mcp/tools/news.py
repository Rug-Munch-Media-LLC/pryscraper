"""Pry - MCP tool definitions: news / sentiment tools and dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from ._common import _call_domain_dispatcher
from ._kwargs_new_domains import _new_domain_tool_kwargs

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_news",
        "description": (
            "Search news articles by keyword across public news feeds and aggregators, "
            "returning title, source, published date, and URL for each result. "
            "Use to monitor a brand, topic, or competitor in the press, e.g. "
            "query='crypto regulation' for the latest regulatory coverage. Best-effort "
            "over free public feeds; never raises and returns an empty list when a feed "
            "is unreachable or rate-limited."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News search keywords, e.g. 'crypto regulation'",
                },
                "language": {
                    "type": "string",
                    "default": "en",
                    "description": "Two-letter article language filter (default: 'en')",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of articles to return (default: 20)",
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
                                    "source": {"type": "string"},
                                    "published_at": {"type": "string"},
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
        "name": "pry_sentiment",
        "description": (
            "Score the sentiment of recent news about a keyword — positive / neutral / "
            "negative with a confidence score — using lightweight text analysis over the "
            "same public news feeds as pry_news. "
            "Use to gauge market or brand mood, e.g. query='Bitcoin ETF' before a trade "
            "or campaign. Degrades to a neutral score when no articles are found; never "
            "raises on feed failures."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic to score, e.g. 'Bitcoin ETF'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of articles analyzed (default: 20)",
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
                        "query": {"type": "string"},
                        "sentiment": {
                            "type": "string",
                            "enum": ["positive", "neutral", "negative"],
                        },
                        "score": {"type": "number"},
                        "confidence": {"type": "number"},
                        "articles_analyzed": {"type": "integer"},
                        "sample_articles": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]

_NEWS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_news": (
        (
            "headlines",
            ("get_headlines", "search_news", "news_search", "search_articles", "get_news"),
        ),
        ("sentiment", ("get_headlines", "search_news", "news_search")),
    ),
    "pry_sentiment": (
        (
            "sentiment",
            ("get_sentiment", "sentiment_analysis", "analyze_sentiment", "news_sentiment"),
        ),
        ("headlines", ("get_sentiment", "sentiment_analysis", "analyze_sentiment")),
    ),
}


async def call_news_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch news MCP tools to their ``news_data`` handlers (guarded).

    The ``news_data`` subpackage (``articles``, ``sentiment``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-news tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "news_data",
        _NEWS_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_news": "query", "pry_sentiment": "query"},
    )
