"""Pry - MCP tool definitions: content filtering / token-cost-aware markdown tools.

Crawl4AI-style filtering: boilerplate removal, main-content extraction,
minimal Markdown conversion, and RAG chunking with token estimates.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_FILTER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_filter_content",
        "description": (
            "Filter HTML to essential content, removing boilerplate and noise. "
            "Strips nav bars, footers, headers, asides, scripts, styles, cookie/GDPR "
            "banners, ad containers, social share widgets, newsletter forms, related "
            "posts, and comment sections — then converts to minimal Markdown with "
            "redundant whitespace collapsed and empty headings dropped. "
            "Use before feeding scraped pages to an LLM to cut token costs by 60-90%: "
            "call with the raw HTML from pry_scrape and get back clean Markdown plus "
            "a token estimate and reduction percentage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": "Raw HTML to filter, e.g. the content from pry_scrape",
                },
                "include_links": {
                    "type": "boolean",
                    "default": True,
                    "description": "Keep hyperlinks as [text](href) in the Markdown output",
                },
                "include_images": {
                    "type": "boolean",
                    "default": False,
                    "description": "Keep images as ![alt](src) in the Markdown output",
                },
            },
            "required": ["html"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "markdown": {
                            "type": "string",
                            "description": "Filtered minimal Markdown content",
                        },
                        "total_tokens": {
                            "type": "integer",
                            "description": "Estimated token count (len/4 approximation)",
                        },
                        "reduction_pct": {
                            "type": "number",
                            "description": "Percentage size reduction vs raw HTML",
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_extract_main",
        "description": (
            "Extract the main content block from a page using readability-style "
            "heuristics. Prioritizes <article>, <main>, [role=main], and common "
            "content containers (.post-content, .entry-content, .article-body); "
            "falls back to the largest text block on the page. Also returns the "
            "page title and how much boilerplate was stripped. "
            "Use when you want just the article body from a cluttered page — "
            "e.g. a news site with sidebars, related-article carousels, and "
            "cookie banners — without writing per-site selectors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": "Raw HTML of the page to extract main content from",
                },
            },
            "required": ["html"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "main_html": {
                            "type": "string",
                            "description": "Extracted main content block as HTML",
                        },
                        "main_text": {
                            "type": "string",
                            "description": "Extracted main content as plain text",
                        },
                        "title": {"type": "string", "description": "Page title"},
                        "reduction_pct": {
                            "type": "number",
                            "description": "Percentage size reduction vs raw HTML",
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_chunk_for_rag",
        "description": (
            "Filter HTML, convert to minimal Markdown, and chunk it for RAG / "
            "vector databases. Full pipeline: boilerplate removal -> minimal "
            "Markdown -> overlapping chunks split on paragraph boundaries. "
            "Returns the chunks, total token estimate, chunk count, and reduction "
            "percentage. Use when indexing scraped pages into a vector DB or "
            "feeding long documents to an LLM with a context budget — e.g. call "
            "with chunk_size=1000 and chunk_overlap=100 to get retrieval-ready "
            "chunks with ~10% overlap for continuity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "html": {
                    "type": "string",
                    "description": "Raw HTML to filter, convert, and chunk",
                },
                "chunk_size": {
                    "type": "integer",
                    "default": 1000,
                    "minimum": 100,
                    "description": "Maximum characters per chunk (default: 1000)",
                },
                "chunk_overlap": {
                    "type": "integer",
                    "default": 100,
                    "minimum": 0,
                    "description": "Characters of overlap between consecutive chunks (default: 100)",
                },
            },
            "required": ["html"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "markdown": {
                            "type": "string",
                            "description": "Filtered minimal Markdown before chunking",
                        },
                        "chunks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Overlapping text chunks ready for embedding",
                        },
                        "total_tokens": {
                            "type": "integer",
                            "description": "Estimated token count of the Markdown",
                        },
                        "chunks_count": {
                            "type": "integer",
                            "description": "Number of chunks produced",
                        },
                        "reduction_pct": {
                            "type": "number",
                            "description": "Percentage size reduction vs raw HTML",
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
]
