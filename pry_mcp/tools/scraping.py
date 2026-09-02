"""Pry - MCP tool definitions: core scraping / extraction / parsing / source-registry tools..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from extraction.css import _validate_css_selector

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

PRY_EXTRACT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_enrich",
        "description": (
            "Enrich a URL with company info, tech stack detection, social profiles, and "
            "competitive intelligence. "
            "Use to build a prospect profile from their website before outreach, e.g. discover "
            "what stack a startup runs and find their LinkedIn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to enrich, e.g. https://startup.example.com",
                }
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
                        "company": {"type": "object"},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                        "social_profiles": {"type": "object"},
                        "emails": {"type": "array", "items": {"type": "string"}},
                        "intelligence": {"type": "object"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_parse_document",
        "description": (
            "Parse a document (PDF, DOCX, image) and extract its text and tables using "
            "pdfplumber, Tesseract OCR, and python-docx. "
            "Use to pull content from a PDF spec, a scanned brochure, or a Word file, e.g. "
            "extract the pricing table from a vendor's PDF."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Direct URL to the document, e.g. https://example.com/spec.pdf",
                }
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
                        "content_type": {"type": "string"},
                        "text": {"type": "string"},
                        "tables": {"type": "array", "items": {"type": "object"}},
                        "pages": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_screenshot",
        "description": (
            "Render a URL in a headless browser and return a screenshot as a "
            "base64-encoded PNG with width, height, and content type. "
            "Use for visual verification or design QA of a rendered page — e.g. "
            "screenshot https://example.com/checkout with full_page=true to capture "
            "the whole checkout flow before launch. JavaScript is executed before "
            "capture so SPAs render correctly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to screenshot, e.g. https://example.com/checkout",
                },
                "full_page": {
                    "type": "boolean",
                    "default": True,
                    "description": "Capture the entire page height instead of just the viewport",
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
                        "image_base64": {"type": "string"},
                        "content_type": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

PRY_SOURCE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_scrape_methods",
        "description": (
            "List the extraction methods Pry uses to scrape sportsbook odds "
            "pages directly: JSON endpoints, __NEXT_DATA__ (Next.js), __NUXT__, "
            "__INITIAL_STATE__ / _dida_config_, HTML tables, and browser "
            "rendering. "
            "Use to understand how each book in the 112-book registry is reached "
            "and which fallback tiers apply, e.g. 'which books need a browser?' "
            "or to audit the no-paid-API scraping layer before building on it."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "methods": {"type": "array", "items": {"type": "string"}},
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_all_sources",
        "description": (
            "Aggregate one event's odds from every reachable source at once: "
            "The Odds API (free tier), ESPN, OddsPortal, Bovada, BetOnline, and "
            "the 112-book sportsbook registry scraped directly via intelligent "
            "fallback — more sources than any other odds service, with no paid "
            "odds API. "
            "Use to get the complete multi-source picture for a single event, "
            "e.g. call with event_id='nba:bda33adc...' and sources='all' to "
            "compare every book and feed on one matchup; the merged result is "
            "deduped with the sharpest line winning conflicts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": (
                        "Event id to aggregate; accepts an optional 'sport:event_id' "
                        "prefix, e.g. 'nba:bda33adc...' (use get_odds to list ids)"
                    ),
                },
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h', 'spreads', 'totals', or a "
                        "comma/pipe separated combo); default is h2h moneyline"
                    ),
                },
                "book": {
                    "type": "string",
                    "description": (
                        "Optional single-book filter (e.g., 'draftkings'); omit "
                        "for every reachable source"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of merged odds records (default: 50)",
                },
                "sources": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Comma-separated source list: the_odds_api, espn, "
                        "oddsportal, bovada, betonline, or 'all' (default) for "
                        "every reachable source"
                    ),
                },
            },
            "required": ["event_id"],
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
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "market": {"type": "string"},
                            "book": {"type": "string"},
                            "source": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
                        },
                    },
                },
                "event_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
]


def validate_schema_selectors(schema: dict[str, Any]) -> dict[str, Any]:
    """Validate every user-supplied CSS selector in an extraction schema.

    ReDoS guard: ``pry_extract`` / ``pry_scrape`` accept a JSON schema whose
    ``base_selector`` and per-field ``selector`` values are passed straight to
    the cssselect engine. This validates them all up front (raising
    ``ValueError`` on the first unsafe selector) so a crafted schema cannot
    reach the extraction engine. Returns the schema unchanged when safe.
    """
    base_selector = schema.get("base_selector")
    if base_selector:
        _validate_css_selector(base_selector)
    for field in schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        field_selector = field.get("selector", "")
        if field_selector:
            _validate_css_selector(field_selector)
    return schema
