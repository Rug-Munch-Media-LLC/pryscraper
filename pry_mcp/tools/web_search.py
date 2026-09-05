"""Pry - MCP tool definitions: Firecrawl-style web search + scrape tools.

Search the web and get the full scraped content of each result page —
not just titles and snippets. Backed by :mod:`pry.engine.web_search`
(SearXNG primary, DuckDuckGo HTML fallback, 15-tier anti-bot scraping).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_SEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_search",
        "description": (
            "Search the web and get the FULL page content of each result — Firecrawl-style "
            "search, not a plain SERP scraper. Each result carries the complete scraped "
            "content and clean markdown of its page, fetched through the 15-tier anti-bot "
            "fallback chain (direct -> cloudscraper -> FlareSolverr -> Playwright -> "
            "Googlebot -> Archive.org -> Google Cache -> Tor -> undetected-chromedriver). "
            "Use when you need to research a topic and read the actual pages, e.g. "
            "search_and_scrape(query='best rust web frameworks 2026', num_results=5) "
            "returns five full articles ready for analysis or RAG ingestion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query, e.g. 'fastapi websocket authentication'",
                },
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Number of results to return and scrape (default: 5)",
                },
                "scrape": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Scrape full page content for each result (default: true). "
                        "Set false to skip scraping and return SERP data only."
                    ),
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
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "title": {"type": "string"},
                                    "snippet": {"type": "string"},
                                    "content": {
                                        "type": "string",
                                        "description": "Full scraped page content",
                                    },
                                    "markdown": {
                                        "type": "string",
                                        "description": "Clean pruned markdown of the page",
                                    },
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
        "name": "pry_search_web",
        "description": (
            "Quick web search returning titles and snippets only — no page scraping. "
            "Fast and cheap: uses self-hosted SearXNG (free, no API key) with a "
            "DuckDuckGo HTML fallback. "
            "Use when you just need to find URLs or get an overview of what's out "
            "there, e.g. search_web(query='site:docs.example.com auth', num_results=10). "
            "For full page content use pry_search instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query, e.g. 'python asyncio rate limiting'",
                },
                "num_results": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Number of results to return (default: 10)",
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
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "title": {"type": "string"},
                                    "snippet": {"type": "string"},
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
        "name": "pry_search_extract",
        "description": (
            "Search the web, scrape each result page, and extract structured JSON data "
            "from every page using your schema — pattern extraction first, LLM fallback "
            "for complex schemas. "
            "Use when you need specific fields from many pages found via search, e.g. "
            "search_and_extract(query='python job postings remote', "
            "schema={'company': 'company name', 'salary': 'salary range', "
            "'location': 'job location'}, num_results=5) returns structured records "
            "from each result page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query, e.g. 'remote rust jobs 2026'",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "Extraction schema mapping field names to descriptions, e.g. "
                        "{'title': 'page title', 'price': 'product price', "
                        "'author': 'article author'}"
                    ),
                },
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Number of results to search, scrape, and extract (default: 5)",
                },
            },
            "required": ["query", "schema"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "title": {"type": "string"},
                                    "data": {
                                        "type": "object",
                                        "description": "Extracted fields matching the schema",
                                    },
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
]

__all__ = ["PRY_SEARCH_TOOLS"]
