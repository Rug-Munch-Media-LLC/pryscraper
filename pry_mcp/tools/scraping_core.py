"""Pry - MCP tool definitions: core scraping / crawling / extraction tools.

Split from the former ``pry_mcp/tools/scraping.py`` god file.
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
        "name": "pry_scrape",
        "description": (
            "Scrape any URL to clean, readable markdown, automatically bypassing Cloudflare, "
            "DataDome, Akamai, and other anti-bot systems via a 15-tier fallback chain "
            "(direct -> cloudscraper -> FlareSolverr -> Playwright -> Googlebot -> "
            "Archive.org -> Google Cache -> Tor -> undetected-chromedriver). "
            "Use when you need the text content of a page a plain HTTP request cannot fetch, "
            "e.g. a Cloudflare-protected article or a JS-heavy blog post."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to scrape, e.g. https://example.com/article",
                },
                "bypass_cloudflare": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use FlareSolverr + Playwright fallback for Cloudflare-protected pages",
                },
                "js_render": {
                    "type": "boolean",
                    "default": False,
                    "description": "Render JavaScript before extracting (slower but handles SPAs)",
                },
                "extract_schema": {
                    "type": "object",
                    "description": (
                        "Optional JSON schema for structured extraction, e.g. "
                        "{fields: [{name, selector, type}]}"
                    ),
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
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string", "description": "Clean markdown content"},
                        "links": {"type": "array", "items": {"type": "string"}},
                        "images": {"type": "array", "items": {"type": "string"}},
                        "status_code": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_crawl",
        "description": (
            "Crawl a website from a seed URL, discovering and scraping linked pages with "
            "BFS/DFS traversal up to max_pages. "
            "Use to collect an entire docs site, blog, or directory — e.g. call with "
            "url='https://example.com' and include_paths=['/docs/'] to harvest every page "
            "under /docs/, or crawl up to 50 blog posts with max_pages=50. "
            "Constrain with include_paths/exclude_paths to stay inside the section you want."
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
                    "default": 10,
                    "minimum": 1,
                    "maximum": 10000,
                    "description": "Maximum number of pages to scrape (default: 10)",
                },
                "max_depth": {
                    "type": "integer",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 20,
                    "description": "Maximum link depth from the seed URL (default: 2)",
                },
                "include_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL path patterns to include (e.g., ['/docs/', '/blog/'])",
                },
                "exclude_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL path patterns to skip (e.g., ['/cart/', '/login'])",
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
                        "pages": {"type": "array", "items": {"type": "object"}},
                        "total_pages": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_extract",
        "description": (
            "Extract structured data from a URL using CSS selectors — 10x cheaper than LLM "
            "extraction — and return JSON matching your schema. "
            "Use when you need specific fields like {title, price, image, availability} from "
            "product listings or search results pages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to extract from, e.g. https://example.com/products",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "Extraction schema with base_selector and fields array, e.g. "
                        "{name: 'product', base_selector: '.product', fields: "
                        "[{name: 'price', selector: '.price', type: 'text'}]}"
                    ),
                    "properties": {
                        "name": {"type": "string"},
                        "base_selector": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "selector": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "text",
                                            "attribute",
                                            "html",
                                            "nested",
                                            "count",
                                            "exists",
                                            "regex",
                                        ],
                                    },
                                    "attribute": {"type": "string"},
                                    "transform": {"type": "string"},
                                },
                                "required": ["name", "selector"],
                            },
                        },
                    },
                    "required": ["name", "fields"],
                },
            },
            "required": ["url", "schema"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_template",
        "description": (
            "Execute one of 110+ pre-built scraper templates (amazon-product, walmart-product, "
            "linkedin-profile, etc.) that return site-specific structured data. "
            "Use when scraping a known site that already has a template instead of hand-writing "
            "CSS selectors — e.g. 'amazon-product' for an Amazon product page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": (
                        "Template ID (e.g., 'amazon-product', 'walmart-product', "
                        "'linkedin-profile') — search with pry_search_templates"
                    ),
                },
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL the template should parse, e.g. https://www.amazon.com/dp/B08N5WRWNW",
                },
            },
            "required": ["template_id", "url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "template_id": {"type": "string"},
                        "url": {"type": "string"},
                        "status_code": {"type": "integer"},
                        "result": {
                            "type": "object",
                            "description": "Template-specific parsed fields (e.g. title, price, availability)",
                        },
                    },
                },
                "error": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_search_templates",
        "description": (
            "Search the 110+ pre-built scraper template catalog by keyword, category, "
            "or site name, returning matching template_ids, their categories, and "
            "descriptions. "
            "Use before pry_template to discover which template fits a target site — "
            "e.g. call with q='walmart' to find 'walmart-product', or q='jobs' with "
            "category='careers' to list every job-board template."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query (e.g., 'amazon', 'jobs', 'real estate')",
                },
                "category": {
                    "type": "string",
                    "description": "Filter templates by category (e.g., 'ecommerce', 'jobs')",
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
                        "templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "template_id": {"type": "string"},
                                    "category": {"type": "string"},
                                    "description": {"type": "string"},
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
