"""Pry - MCP tool definitions: app-store tools and dispatcher..

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
        "name": "pry_app_search",
        "description": (
            "Search the Apple App Store by keyword and return matching apps — name, "
            "bundle id, price, rating, category, and store URL. "
            "Use to find apps by feature, compare pricing across categories, or feed "
            "app-market research, e.g. search query='crypto wallet' to list every mobile "
            "wallet on the store. Backed by the free public iTunes Search API; never "
            "raises and returns an empty list when the feed is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "App store search keywords, e.g. 'crypto wallet'",
                },
                "country": {
                    "type": "string",
                    "default": "us",
                    "description": "Two-letter store country code (default: 'us')",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of apps to return (default: 20)",
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
                        "Matching apps in relevance order; empty when the iTunes feed "
                        "is unreachable or nothing matches."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "app_id": {"type": ["integer", "null"]},
                            "title": {"type": "string"},
                            "developer": {"type": "string"},
                            "genre": {"type": "string"},
                            "rating": {"type": ["number", "null"]},
                            "rating_count": {"type": ["integer", "null"]},
                            "price": {"type": "string"},
                            "version": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_app_reviews",
        "description": (
            "Get recent user reviews for an app by its store identifier — the numeric App "
            "Store id or bundle id, e.g. 'com.coinbase.app' — returning rating, title, "
            "body, author, and review date for each. "
            "Use to gauge app sentiment, triage support complaints, or feed product-"
            "research pipelines, e.g. reviews for '284910350' (Coinbase). Reads the free "
            "public App Store customer reviews feed; never raises and returns an empty "
            "list when the feed is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app_id": {
                    "type": "string",
                    "description": (
                        "App Store numeric id or bundle id, e.g. '284910350' or 'com.coinbase.app'"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum number of reviews to return (default: 20)",
                },
            },
            "required": ["app_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "description": (
                        "Recent reviews, newest first; empty when the reviews feed is unreachable."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "author": {"type": "string"},
                            "rating": {"type": ["number", "null"]},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "date": {"type": "string"},
                            "version": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]

_APP_STORE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_app_search": (("apple", ("search_apps", "app_search", "search_products", "search")),),
    "pry_app_reviews": (("apple", ("get_reviews", "app_reviews", "get_app_reviews")),),
}


async def call_app_store_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch app-store MCP tools to their ``app_store_data`` handlers (guarded).

    The ``app_store_data`` subpackage (``search``, ``reviews``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-app-store tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "app_store_data",
        _APP_STORE_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_app_search": "query", "pry_app_reviews": "app_id"},
    )
