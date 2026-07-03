"""Pry - MCP tool definitions.

PRY_TOOLS list with all scraper templates.

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

PRY_TOOLS = [
    {
        "name": "pry_scrape",
        "description": "Scrape a URL to clean markdown. Bypasses Cloudflare, DataDome, Akamai, and other anti-bot systems automatically using a 9-tier fallback (direct → cloudscraper → FlareSolverr → Playwright → Googlebot → Archive.org → Google Cache → Tor → undetected-chromedriver).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri", "description": "URL to scrape"},
                "bypass_cloudflare": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use FlareSolverr + Playwright fallback",
                },
                "js_render": {
                    "type": "boolean",
                    "default": False,
                    "description": "Render JavaScript (slower but handles SPAs)",
                },
                "extract_schema": {
                    "type": "object",
                    "description": "Optional JSON schema for structured extraction (e.g., {fields: [{name, selector, type}]})",
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
        "description": "Crawl a website starting from a URL. Discovers and scrapes linked pages up to max_pages with BFS/DFS traversal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "max_pages": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 10000,
                },
                "max_depth": {
                    "type": "integer",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 20,
                },
                "include_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL path patterns to include (e.g., ['/docs/', '/blog/'])",
                },
                "exclude_paths": {"type": "array", "items": {"type": "string"}},
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
        },
    },
    {
        "name": "pry_extract",
        "description": "Extract structured data from a URL using CSS selectors. 10x cheaper than LLM extraction. Returns JSON matching the schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "schema": {
                    "type": "object",
                    "description": "Extraction schema with base_selector and fields array",
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
        "description": "Execute one of 110+ pre-built scraper templates (amazon-product, walmart-product, linkedin-profile, etc.). Returns structured data matching the site's schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Template ID (e.g., 'amazon-product', 'walmart-product', 'linkedin-profile')",
                },
                "url": {"type": "string", "format": "uri"},
            },
            "required": ["template_id", "url"],
        },
    },
    {
        "name": "pry_search_templates",
        "description": "Search across all 110+ available scraper templates by keyword, category, or site.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query (e.g., 'amazon', 'jobs', 'real estate')",
                },
                "category": {"type": "string", "description": "Filter by category"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "pry_monitor",
        "description": "Create a content change monitor. Get notified via webhook, Slack, or Discord when a page changes. AI judges if changes are meaningful.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "schedule_cron": {
                    "type": "string",
                    "default": "0 */6 * * *",
                    "description": "Cron expression (default: every 6 hours)",
                },
                "webhook_url": {"type": "string", "format": "uri"},
                "goal": {
                    "type": "string",
                    "description": "Natural language goal for AI change judging (e.g., 'price changes matter, not descriptions')",
                },
            },
            "required": ["name", "url"],
        },
    },
    {
        "name": "pry_compliance",
        "description": "Check legal compliance for scraping a URL. Analyzes robots.txt, ToS, GDPR/CCPA, and PII exposure. Returns green/yellow/red risk score with recommendations.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_enrich",
        "description": "Enrich a URL with company info, tech stack detection, social profiles, and competitive intelligence.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_parse_document",
        "description": "Parse a document (PDF, DOCX, image) and extract text/tables. Uses pdfplumber, Tesseract OCR, and python-docx.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "pry_screenshot",
        "description": "Take a full-page screenshot of a URL. Returns base64-encoded PNG. Useful for visual analysis and OCR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "full_page": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    },
    {
        "name": "pry_x402_pricing",
        "description": "Get current x402 pay-per-call pricing for all Pry operations. Shows the cost in USDC atomic units for each tool.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "pricing": {"type": "object"},
                        "wallet": {"type": "string"},
                        "facilitator": {"type": "string"},
                        "supported_networks": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_referrals",
        "description": "Get Pry's referral catalog (60+ providers across LLM, hosting, email, monitoring, proxies, devtools). Each link includes our affiliate ID for revenue attribution.",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
        },
    },
]
