"""Pry - MCP tool definitions: Firecrawl-style site mapping + crawl-to-markdown tools.

Domain mapping (sitemap + crawl URL discovery), clean Markdown conversion,
and RAG-ready chunking for vector databases. Backed by
``pry.engine.site_mapper``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_map_site",
        "description": (
            "Map an entire domain: discover all URLs via sitemap.xml (including "
            "sitemap indexes) plus internal-link crawling, Firecrawl-style. "
            "Use before crawling or scraping a whole site to see its full URL "
            "structure — e.g. call with url='https://example.com' and "
            "max_urls=100 to list every discoverable page on the domain. "
            "Sitemap-first discovery is fast and polite; link crawling fills "
            "any remaining budget when no sitemap exists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Base URL of the domain to map, e.g. https://example.com",
                },
                "max_urls": {
                    "type": "integer",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 10000,
                    "description": "Maximum number of URLs to discover (default: 100)",
                },
                "follow_sitemap": {
                    "type": "boolean",
                    "default": True,
                    "description": "Check sitemap.xml first before link crawling (default: true)",
                },
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Discovered URLs on the domain",
                        },
                        "total": {"type": "integer"},
                        "sitemap_found": {
                            "type": "boolean",
                            "description": "Whether a sitemap.xml was found and used",
                        },
                        "crawled": {
                            "type": "boolean",
                            "description": "Whether internal-link crawling contributed URLs",
                        },
                        "base_url": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_crawl_to_markdown",
        "description": (
            "Crawl a site and convert every page to clean, chunked Markdown — "
            "Firecrawl-style output ready for vector databases. Maps the "
            "domain, fetches each page through the anti-bot fallback chain "
            "(Cloudflare/DataDome bypass), prunes nav/footer/boilerplate "
            "noise, and splits content into ~chunk_size character chunks. "
            "Use to harvest an entire docs site or blog as structured "
            "Markdown — e.g. call with url='https://example.com/docs' and "
            "max_pages=50 to convert the docs section to Markdown chunks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Seed URL to start crawling from, e.g. https://example.com",
                },
                "max_pages": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum number of pages to crawl and convert (default: 50)",
                },
                "chunk_size": {
                    "type": "integer",
                    "default": 1000,
                    "minimum": 100,
                    "maximum": 100000,
                    "description": "Target chunk size in characters (default: 1000)",
                },
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "pages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "markdown": {
                                        "type": "string",
                                        "description": "Clean pruned Markdown for the page",
                                    },
                                    "chunks": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Markdown split into ~chunk_size chunks",
                                    },
                                    "title": {"type": "string"},
                                },
                            },
                        },
                        "total_pages": {"type": "integer"},
                        "total_chunks": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_crawl_for_rag",
        "description": (
            "Crawl a site and produce RAG-ready chunks for vector databases — "
            "each chunk carries provenance metadata (source URL, page title, "
            "chunk index, token estimate) so embeddings stay traceable to "
            "their origin. Uses overlapping chunks (chunk_overlap) to preserve "
            "context across boundaries. Use when building a RAG pipeline over "
            "a website — e.g. call with url='https://example.com' and "
            "chunk_size=1000, chunk_overlap=100 to get embedding-ready chunks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Seed URL to start crawling from, e.g. https://example.com",
                },
                "max_pages": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum number of pages to crawl (default: 50)",
                },
                "chunk_size": {
                    "type": "integer",
                    "default": 1000,
                    "minimum": 100,
                    "maximum": 100000,
                    "description": "Target chunk size in characters (default: 1000)",
                },
                "chunk_overlap": {
                    "type": "integer",
                    "default": 100,
                    "minimum": 0,
                    "maximum": 10000,
                    "description": "Character overlap between consecutive chunks (default: 100)",
                },
            },
            "required": ["url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "chunks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "Chunk text ready for embedding",
                                    },
                                    "url": {
                                        "type": "string",
                                        "description": "Source page URL (provenance)",
                                    },
                                    "title": {"type": "string"},
                                    "chunk_index": {"type": "integer"},
                                    "token_estimate": {
                                        "type": "integer",
                                        "description": "Estimated tokens (len(content) // 4)",
                                    },
                                },
                                "required": ["content", "url", "chunk_index"],
                            },
                        },
                        "total_chunks": {"type": "integer"},
                        "total_pages": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]
