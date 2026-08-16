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

import json
from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_scrape",
        "description": (
            "Scrape any URL to clean, readable markdown, automatically bypassing Cloudflare, "
            "DataDome, Akamai, and other anti-bot systems via a 9-tier fallback chain "
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
    {
        "name": "pry_monitor",
        "description": (
            "Create a content-change monitor that notifies via webhook, Slack, or Discord when "
            "a page changes, using AI to judge whether changes are meaningful. "
            "Use to track competitor pricing or product availability over time, e.g. "
            "'notify me when this price page changes'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable monitor name, e.g. 'Competitor pricing watch'",
                },
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The page to monitor for changes, e.g. https://example.com/pricing",
                },
                "schedule_cron": {
                    "type": "string",
                    "default": "0 */6 * * *",
                    "description": "Cron expression (default: every 6 hours)",
                },
                "webhook_url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Webhook/Slack/Discord URL to notify on meaningful changes",
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "Natural language goal for AI change judging (e.g., 'price changes "
                        "matter, not descriptions')"
                    ),
                },
            },
            "required": ["name", "url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string"},
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "schedule_cron": {"type": "string"},
                        "webhook_url": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
                "error": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_compliance",
        "description": (
            "Check whether scraping a URL is legally safe by analyzing robots.txt, ToS, "
            "GDPR/CCPA, and PII exposure, returning a green/yellow/red risk score with "
            "recommendations. "
            "Use before scraping a site you are unsure about, e.g. a competitor's member-only "
            "directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to run a compliance check on, e.g. https://example.com",
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
                        "risk_level": {
                            "type": "string",
                            "enum": ["green", "yellow", "red"],
                        },
                        "risk_score": {"type": "number"},
                        "checks": {"type": "array", "items": {"type": "object"}},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
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
    {
        "name": "pry_x402_pricing",
        "description": (
            "Get current x402 pay-per-call pricing for all Pry operations, showing the cost in "
            "USDC atomic units and supported networks for each tool. "
            "Use before a paid call to display the cost to the user, e.g. 'how much does a "
            "pry_scrape cost?'."
        ),
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
        "description": (
            "Get Pry's referral catalog — 60+ providers across LLM, hosting, email, "
            "monitoring, proxies, and devtools — each link carrying our affiliate ID for "
            "revenue attribution. "
            "Use to find a revenue-share partner or pick a recommended provider, e.g. "
            "'what proxy providers do you refer?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter the catalog by category (e.g., 'proxies', 'llm', 'hosting')",
                }
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "providers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "category": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_token_launches",
        "description": (
            "Discover new crypto token launches, new liquidity pairs, and trending tokens "
            "across chains (Solana, Ethereum, Base, ...) with optional age filtering. "
            "Use to find early-stage tokens before they hit mainstream trackers, e.g. "
            "'what new Solana tokens launched in the last hour?' or 'show me trending "
            "tokens on Base'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Blockchain filter (e.g., 'solana', 'ethereum', 'base', 'all'). "
                        "Use 'all' to search every supported chain."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of results to return (default: 50)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["tokens", "pairs", "trending"],
                    "default": "tokens",
                    "description": (
                        "What to return: 'tokens' = newly created tokens, "
                        "'pairs' = new liquidity pairs, 'trending' = currently trending tokens"
                    ),
                },
            },
            "required": [],
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
                                    "address": {"type": "string"},
                                    "symbol": {"type": "string"},
                                    "name": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "created_at": {"type": "string"},
                                    "liquidity_usd": {"type": "number"},
                                    "volume_24h_usd": {"type": "number"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "chain": {"type": "string"},
                        "kind": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_cex_listings",
        "description": (
            "Get recent centralized-exchange (CEX) listing and delisting signals — e.g. "
            "Binance, Coinbase, Kraken — aggregated over a configurable lookback window. "
            "Use to time research on tokens that just landed on a major exchange, e.g. "
            "'what did Coinbase list in the last 24 hours?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "exchanges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "CEX names to filter by (e.g., ['binance', 'coinbase', 'kraken']). "
                        "Omit or pass [] to include every tracked exchange."
                    ),
                },
                "lookback_hours": {
                    "type": "integer",
                    "default": 24,
                    "minimum": 1,
                    "maximum": 720,
                    "description": "Look back window in hours (default: 24)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "signals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "token_symbol": {"type": "string"},
                                    "token_address": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "exchange": {"type": "string"},
                                    "event": {"type": "string"},
                                    "announced_at": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "lookback_hours": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_amazon_product",
        "description": (
            "Look up a single Amazon product by its ASIN (e.g. 'B08N5WRWNW') and return "
            "current price, title, availability, rating, and listing details from the "
            "marketplace intelligence provider. "
            "Use to check a product's live price or stock, e.g. 'what does B0BLVMHNF1 "
            "cost right now?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "asin": {
                    "type": "string",
                    "description": (
                        "Amazon Standard Identification Number (10-character "
                        "alphanumeric), e.g. 'B08N5WRWNW'"
                    ),
                },
            },
            "required": ["asin"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "asin": {"type": "string"},
                        "title": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "availability": {"type": "string"},
                        "rating": {"type": "number"},
                        "reviews_count": {"type": "integer"},
                        "url": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_amazon_search",
        "description": (
            "Search Amazon products by keyword and return matching listings — title, "
            "price, rating, and ASIN for each result (up to limit). "
            "Use to compare prices or discover products, e.g. 'search Amazon for "
            "wireless mechanical keyboards'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords, e.g. 'wireless mechanical keyboard'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of results to return (default: 20)",
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
                                    "asin": {"type": "string"},
                                    "title": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "rating": {"type": "number"},
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
        "name": "pry_walmart_product",
        "description": (
            "Look up a single Walmart product by its product ID (e.g. '4JH7P89H7X5P') "
            "and return current price, title, availability, seller, and rating from the "
            "marketplace intelligence provider. "
            "Use to check a Walmart listing's live price or stock, e.g. 'what does "
            "Walmart product 4JH7P89H7X5P cost?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": ("Walmart product ID (alphanumeric), e.g. '4JH7P89H7X5P'"),
                },
            },
            "required": ["product_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "title": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "availability": {"type": "string"},
                        "seller": {"type": "string"},
                        "rating": {"type": "number"},
                        "url": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_tiktok_trending",
        "description": (
            "Get currently trending products on TikTok Shop, ranked by engagement and "
            "sales velocity, with price, sales count, and shop info for each result "
            "(up to limit). "
            "Use to spot viral commerce opportunities, e.g. 'what's trending on TikTok "
            "Shop right now?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of trending items to return (default: 50)",
                },
            },
            "required": [],
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
                                    "product_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "sales_count": {"type": "integer"},
                                    "shop_name": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_token_security",
        "description": (
            "Run a security scan on a crypto token by chain and contract/mint address — "
            "checking for honeypots, hidden mints, ownership concentration, LP lock, and "
            "other rug-pull risk signals. "
            "Use before investing in or reporting on an unfamiliar token, e.g. 'scan "
            "So11111111111111111111111111111111111111112 on solana'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "description": (
                        "Blockchain the token lives on (e.g., 'solana', 'ethereum', 'base')"
                    ),
                },
                "address": {
                    "type": "string",
                    "description": (
                        "Token contract or mint address, e.g. "
                        "'So11111111111111111111111111111111111111112'"
                    ),
                },
            },
            "required": ["chain", "address"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "chain": {"type": "string"},
                        "address": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "risk_level": {"type": "string"},
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_legal_dockets",
        "description": (
            "Search U.S. federal and state court dockets by full-text query using the free "
            "CourtListener REST API v4, returning docket titles, courts, and case numbers. "
            "Use to monitor litigation against a company, person, or trademark before it "
            "hits the news, e.g. 'what lawsuits involve OpenAI?' or 'show dockets mentioning "
            "this company name'. Results are best-effort: the free tier has no auth and "
            "degrades to an empty list on network or rate-limit failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full-text docket search query, e.g. 'OpenAI copyright infringement'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of dockets to return (default: 20)",
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
                            "id": {"type": "integer"},
                            "case_name": {"type": "string"},
                            "court": {"type": "string"},
                            "docket_number": {"type": "string"},
                            "date_filed": {"type": "string"},
                            "url": {"type": "string"},
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
        "name": "pry_legal_sec",
        "description": (
            "Search SEC EDGAR filings for a public company by ticker and form type, returning "
            "filing dates, form names, and EDGAR accession numbers. Use to track regulatory "
            "filings that move markets, e.g. 'recent 8-K filings for AAPL' or 'all 10-Q "
            "filings for TSLA this year'. Backed by the free EDGAR Full-Text Search and "
            "submissions feed; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Company ticker symbol, e.g. 'AAPL'",
                },
                "form_type": {
                    "type": "string",
                    "default": "8-K",
                    "description": "SEC form type to search (e.g. '8-K', '10-Q', '10-K', '4')",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of filings to return (default: 20)",
                },
            },
            "required": ["ticker"],
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
                            "accession_no": {"type": "string"},
                            "form_type": {"type": "string"},
                            "filing_date": {"type": "string"},
                            "ticker": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "ticker": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_legal_sanctions",
        "description": (
            "Screen a person or entity name against the OFAC Specially Designated Nationals "
            "(SDN) sanctions list, returning any matching records with their sanctions "
            "program and remarks. Use for compliance due diligence before onboarding a "
            "counterparty, partner, or wallet-linked entity, e.g. 'is Vladimir Potanin "
            "sanctioned?'. Backed by the free OFAC SDN XML downloads, cached in-process; "
            "returns an empty list when the name is clean or the feed is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person or entity name to screen, e.g. 'Vladimir Potanin'",
                }
            },
            "required": ["name"],
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
                            "name": {"type": "string"},
                            "program": {"type": "string"},
                            "remarks": {"type": "string"},
                            "uid": {"type": "string"},
                        },
                    },
                },
                "name": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_realestate_search",
        "description": (
            "Search real-estate listings by location and status (for_sale, for_rent, sold), "
            "returning address, price, beds/baths, square footage, and listing URLs. "
            "Use for market research, comps, or lead generation, e.g. 'what's for sale in "
            "Austin, TX under $500k?'. Scrapes Zillow search pages with a Redfin GIS API "
            "fallback (both free and keyless); never raises and returns an empty list when "
            "the source is unreachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or neighborhood, e.g. 'Austin, TX'",
                },
                "status": {
                    "type": "string",
                    "enum": ["for_sale", "for_rent", "sold"],
                    "default": "for_sale",
                    "description": "Listing status filter (default: for_sale)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum number of listings to return (default: 20)",
                },
            },
            "required": ["location"],
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
                            "zpid": {"type": "string"},
                            "address": {"type": "string"},
                            "price": {"type": "number"},
                            "beds": {"type": "integer"},
                            "baths": {"type": "number"},
                            "sqft": {"type": "integer"},
                            "status": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "location": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_jobs_list",
        "description": (
            "List current job postings for a company from its applicant-tracking system "
            "(Greenhouse, Lever, Ashby, or Workday), returning normalized titles, locations, "
            "remote flags, and application URLs. Use for talent-market intel or recruitment "
            "pipelines, e.g. 'what engineering roles is Stripe hiring for?'. Reads the free, "
            "public, keyless JSON boards; never raises and returns an empty list when the "
            "board is unreachable or the company slug is unknown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company slug on the ATS board, e.g. 'stripe'",
                },
                "board": {
                    "type": "string",
                    "enum": ["greenhouse", "lever", "ashby", "workday"],
                    "default": "greenhouse",
                    "description": "ATS board to query (default: greenhouse)",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of listings to return (default: 50)",
                },
            },
            "required": ["company"],
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
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "company": {"type": "string"},
                            "location": {"type": "string"},
                            "remote": {"type": "boolean"},
                            "url": {"type": "string"},
                            "posted_at": {"type": "string"},
                        },
                    },
                },
                "board": {"type": "string"},
                "total": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_jobs_salary",
        "description": (
            "Get per-level salary bands (total compensation, base, stock, bonus) for a "
            "company and role from Levels.fyi's public embedded data. Use to benchmark "
            "compensation offers or market rates, e.g. 'what does Google pay software "
            "engineers at L5?'. Scrapes the free Levels.fyi page with no auth; never "
            "raises and returns an empty object when the company or role is not found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company slug, e.g. 'google'",
                },
                "role": {
                    "type": "string",
                    "default": "software_engineer",
                    "description": "Role slug, e.g. 'software_engineer', 'product_manager'",
                },
            },
            "required": ["company"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "role": {"type": "string"},
                        "levels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "level": {"type": "string"},
                                    "total_comp": {"type": "number"},
                                    "base": {"type": "number"},
                                    "stock": {"type": "number"},
                                    "bonus": {"type": "number"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_flights_grid",
        "description": (
            "Get the cheapest flight option per day between two dates for an origin and "
            "destination pair, using Google Flights' public tfs deep-link page. Use to find "
            "the cheapest day to fly on a trip, e.g. 'what's the cheapest day JFK→CDG next "
            "month?'. Returns a per-day price grid; never raises and returns an empty grid "
            "when Google Flights blocks the scrape (embedded JSON drifts over time)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "IATA origin code, e.g. 'JFK'",
                },
                "dest": {
                    "type": "string",
                    "description": "IATA destination code, e.g. 'CDG'",
                },
                "start_date": {
                    "type": "string",
                    "description": "First date (YYYY-MM-DD), e.g. '2026-09-01'",
                },
                "end_date": {
                    "type": "string",
                    "description": "Last date (YYYY-MM-DD), e.g. '2026-09-30'",
                },
            },
            "required": ["origin", "dest", "start_date", "end_date"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string"},
                        "dest": {"type": "string"},
                        "days": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "price_usd": {"type": "number"},
                                    "airline": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_hotel_rates",
        "description": (
            "Get per-night hotel rates for a stay window from Google Hotels with a "
            "Booking.com fallback, both free and keyless page scrapes. Use to compare "
            "prices across sources for a specific property, e.g. 'what does the Ritz Paris "
            "cost for September 10-14?'. Returns per-night rate breakdowns; never raises "
            "and returns an empty object when neither source is reachable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hotel_name": {
                    "type": "string",
                    "description": "Hotel name or location query, e.g. 'Ritz Paris'",
                },
                "checkin": {
                    "type": "string",
                    "description": "Check-in date (YYYY-MM-DD), e.g. '2026-09-10'",
                },
                "checkout": {
                    "type": "string",
                    "description": "Check-out date (YYYY-MM-DD), e.g. '2026-09-14'",
                },
            },
            "required": ["hotel_name", "checkin", "checkout"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "hotel": {"type": "string"},
                        "nights": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "price_usd": {"type": "number"},
                                    "source": {"type": "string"},
                                },
                            },
                        },
                        "total_usd": {"type": "number"},
                    },
                },
            },
            "required": ["success"],
        },
    },
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
    {
        "name": "pry_procurement",
        "description": (
            "Search U.S. federal procurement opportunities and contract awards from the "
            "public SAM.gov data feed, returning title, agency, notice type, and deadline. "
            "Use to find government business opportunities for a capability, e.g. 'what "
            "cybersecurity contracts are open?'. The gov_data module is built in parallel; "
            "until it lands this tool returns a readable not-available message instead of "
            "erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'cybersecurity'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
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
                            "notice_id": {"type": "string"},
                            "title": {"type": "string"},
                            "agency": {"type": "string"},
                            "notice_type": {"type": "string"},
                            "deadline": {"type": "string"},
                            "url": {"type": "string"},
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
        "name": "pry_recalls",
        "description": (
            "Search recent product recalls from the U.S. CPSC public data feed, returning "
            "product name, hazard, recall date, and remedy. Use for consumer-safety "
            "monitoring or supply-chain due diligence, e.g. 'recent recalls for e-bike "
            "batteries'. The gov_data module is built in parallel; until it lands this "
            "tool returns a readable not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'e-bike battery'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
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
                            "recall_id": {"type": "string"},
                            "product": {"type": "string"},
                            "hazard": {"type": "string"},
                            "recall_date": {"type": "string"},
                            "remedy": {"type": "string"},
                            "url": {"type": "string"},
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
        "name": "pry_patents",
        "description": (
            "Search U.S. patents by keyword using the USPTO public data feeds, returning "
            "patent number, title, assignee, and grant date. Use for IP landscaping or "
            "freedom-to-operate checks, e.g. 'patents for blockchain identity'. The ip_data "
            "module is built in parallel; until it lands this tool returns a readable "
            "not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search, e.g. 'blockchain identity'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
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
                            "patent_number": {"type": "string"},
                            "title": {"type": "string"},
                            "assignee": {"type": "string"},
                            "grant_date": {"type": "string"},
                            "url": {"type": "string"},
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
        "name": "pry_trademarks",
        "description": (
            "Search U.S. trademarks by keyword or owner using the USPTO public data feeds, "
            "returning serial number, mark text, owner, and status. Use for brand "
            "clearance before launching a product or token name, e.g. 'is RugMunch "
            "trademarked?'. The ip_data module is built in parallel; until it lands this "
            "tool returns a readable not-available message instead of erroring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or owner search, e.g. 'RugMunch'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum results to return (default: 20)",
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
                            "serial_number": {"type": "string"},
                            "mark": {"type": "string"},
                            "owner": {"type": "string"},
                            "status": {"type": "string"},
                            "url": {"type": "string"},
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
        "name": "pry_odds",
        "description": (
            "Get live betting odds across major bookmakers (DraftKings, FanDuel, "
            "BetMGM, ESPN BET, ...) for one or more sports, backed by The Odds API "
            "(free tier via PRY_ODDS_API_KEY) with an ESPN scoreboard fallback. "
            "Each record includes the event label, market, bookmaker, and decimal "
            "odds for home/away. "
            "Use to compare lines before placing a bet or to power an odds "
            "aggregator, e.g. 'what are the current NBA moneyline odds across "
            "books?' or call with sport='nfl' to see the full NFL slate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default: nba + nfl + epl)"
                    ),
                },
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h' moneyline, 'spreads', "
                        "'totals'); the default feed is h2h moneyline"
                    ),
                },
                "book": {
                    "type": "string",
                    "description": (
                        "Bookmaker name filter (e.g., 'DraftKings', 'FanDuel', "
                        "'BetMGM'); omit for every book"
                    ),
                },
                "event_query": {
                    "type": "string",
                    "description": "Substring filter on event label, e.g. 'celtics'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of odds records (default: 20)",
                },
            },
            "required": [],
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
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_arbitrage",
        "description": (
            "Scan sportsbook lines for guaranteed-profit arbitrage opportunities: "
            "the same event quoted at different books where the combined implied "
            "probabilities total under 100%. "
            "Use to find risk-free bets, e.g. 'show me NFL arbitrage opportunities "
            "with at least 0.8% yield' or call with sport='all' to sweep every "
            "tracked league."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "min_yield_pct": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0,
                    "maximum": 100,
                    "description": ("Minimum guaranteed yield in percent to report (default: 0.5)"),
                },
            },
            "required": [],
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
                            "event_id": {"type": "string"},
                            "yield_pct": {"type": "number"},
                            "legs": {"type": "array", "items": {"type": "object"}},
                        },
                    },
                },
                "sport": {"type": "string"},
                "min_yield_pct": {"type": "number"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_plus_ev",
        "description": (
            "Find positive expected-value (+EV) betting opportunities by comparing "
            "market odds against a sharp book's line or consensus price. "
            "Use to identify bets where the market price is better than the fair "
            "probability implies, e.g. 'what are the best +EV bets right now?' or "
            "call with sharp_book='pinnacle' and min_ev_pct=2.0 to only see edges "
            "above 2%."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sharp_book": {
                    "type": "string",
                    "default": "pinnacle",
                    "description": (
                        "Sharp book to treat as the fair line reference "
                        "(e.g., 'pinnacle', 'circa', 'betonline')"
                    ),
                },
                "min_ev_pct": {
                    "type": "number",
                    "default": 1.0,
                    "minimum": 0,
                    "maximum": 100,
                    "description": ("Minimum expected value in percent to report (default: 1.0)"),
                },
            },
            "required": [],
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
                            "event_id": {"type": "string"},
                            "ev_pct": {"type": "number"},
                            "sharp_book": {"type": "string"},
                            "best_book": {"type": "string"},
                            "price": {"type": "number"},
                        },
                    },
                },
                "sharp_book": {"type": "string"},
                "min_ev_pct": {"type": "number"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_props",
        "description": (
            "Get player prop betting lines (points, rebounds, assists, yards, "
            "strikeouts, ...) for a player or sport, with the market and book "
            "prices. "
            "Use to research player props before betting or building a props "
            "dashboard, e.g. 'what are LeBron James points props tonight?' or call "
            "with sport='nfl' and market='passing_yards' to see QB yardage props."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player": {
                    "type": "string",
                    "description": "Player name, e.g. 'LeBron James'",
                },
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "market": {
                    "type": "string",
                    "description": (
                        "Prop market (e.g., 'points', 'rebounds', 'passing_yards', "
                        "'strikeouts'); omit for every market"
                    ),
                },
            },
            "required": [],
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
                            "player": {"type": "string"},
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "line": {"type": "number"},
                            "over_price": {"type": "number"},
                            "under_price": {"type": "number"},
                        },
                    },
                },
                "player": {"type": "string"},
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_injuries",
        "description": (
            "Get the current injury report for a sport or team: player, team, "
            "injury detail, and status (out/questionable/active). "
            "Use to adjust betting models or fantasy lineups before lock, e.g. "
            "'who is out for the Celtics tonight?' or call with sport='nfl' for "
            "the full league injury report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "team": {
                    "type": "string",
                    "description": (
                        "Team name to filter by (e.g., 'Celtics', 'Chiefs'); omit for every team"
                    ),
                },
            },
            "required": [],
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
                            "player": {"type": "string"},
                            "team": {"type": "string"},
                            "sport": {"type": "string"},
                            "injury": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "team": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_live_odds",
        "description": (
            "Get live in-play odds that update during games (moneyline, spreads, "
            "totals as they move). "
            "Use for live-betting research or game-flow monitoring, e.g. 'what are "
            "the live odds for the Lakers game right now?' or call with sport='nba' "
            "and limit=50 for the current in-play slate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of live odds records (default: 20)",
                },
            },
            "required": [],
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
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "bookmaker": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "last_update": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_scores",
        "description": (
            "Get final or live scores for one or more sports on a given day from "
            "ESPN public scoreboards (free, no quota, high-frequency safe). "
            "Use to check results or power a scores widget, e.g. 'what were the "
            "NBA scores on 20260815?' or call with sport='mlb' and date='today' "
            "for today's baseball scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "all",
                    "description": (
                        "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, "
                        "ufc, cfl, or 'all' (default: nba + nfl + epl)"
                    ),
                },
                "date": {
                    "type": "string",
                    "default": "today",
                    "description": ("Date: 'today' (default), YYYYMMDD, or YYYY-MM-DD"),
                },
            },
            "required": [],
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
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "home_score": {"type": "string"},
                            "away_score": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]


# ── MCP 2025-11-25 tool annotations ────────────────────────────────────
# Every tool must declare ``readOnlyHint`` / ``destructiveHint`` /
# ``idempotentHint`` so clients (Claude, Cursor, Hermes, agent SDKs) can
# reason about side effects before calling. Defaults: read-only (no server
# state mutation), non-destructive, idempotent (repeated calls are safe).
# Tools that mutate server state opt out explicitly.
#
# Audit (2026-08-16, all 42 PRY_TOOLS):
#   * pry_monitor  — persists a scheduled monitor on the server:
#     readOnlyHint=False, idempotentHint=False. destructiveHint stays False:
#     it never deletes data (removal is a separate /v1/monitor/{id} DELETE).
#   * pry_referrals — audited: GET /v1/referrals/catalog reads the static
#     PROVIDER_CATALOG; it does NOT record clicks/conversions
#     (ReferralTracker.record_click is a different route), so it keeps the
#     read-only, idempotent default.
#   * The 7 sports-betting tools (pry_odds, pry_arbitrage, pry_plus_ev,
#     pry_props, pry_injuries, pry_live_odds, pry_scores) are pure reads of
#     The Odds API / ESPN feeds — no server-state changes, so they keep the
#     default read-only, non-destructive, idempotent annotations.
#   * The remaining 33 tools are reads/scrapes with no server-state changes —
#     the default read-only, non-destructive, idempotent annotations apply.
_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    # pry_monitor persists a scheduled monitor on the server.
    "pry_monitor": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
}


def _annotations_for(name: str) -> dict[str, bool]:
    """Return the MCP annotation triple for a tool name (default: read-only)."""
    if name in _TOOL_ANNOTATIONS:
        return _TOOL_ANNOTATIONS[name]
    return {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}


for _tool in PRY_TOOLS:
    _tool.setdefault("annotations", _annotations_for(str(_tool["name"])))

# Frozen set of every registered tool name — used by the registry-sync tests
# to assert server.json / glama.json / pulsemcp.json / llms.txt stay in sync.
PRY_TOOL_NAMES: frozenset[str] = frozenset(str(t["name"]) for t in PRY_TOOLS)


def _crypto_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a crypto tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Tool {tool_name} is not available yet: the crypto_market module has "
                    "not finished landing (parallel build in progress). Try again shortly."
                ),
            }
        ],
        "isError": False,
    }


async def call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the crypto-market MCP tools to their ``crypto_market`` handlers.

    The ``crypto_market`` subpackage (``token_launches``, ``cex_listings``,
    ``token_security``) is built in parallel by other agents; every import is
    guarded so this dispatcher degrades gracefully (a readable message) if a
    module has not landed yet. Returns ``None`` for non-crypto tools so callers
    fall through to their normal execution path (remote executor / REST proxy).
    """
    if name == "pry_token_launches":
        kind = arguments.get("kind", "tokens")
        chain = arguments.get("chain", "all")
        limit = int(arguments.get("limit", 50))
        try:
            from crypto_market.token_launches import (
                get_new_pairs,
                get_new_tokens,
                get_trending_tokens,
            )
        except ImportError:
            return _crypto_module_unavailable(name)
        fn = {
            "tokens": get_new_tokens,
            "pairs": get_new_pairs,
            "trending": get_trending_tokens,
        }.get(kind, get_new_tokens)
        launches_data = await fn(chain=chain, limit=limit)
        return {
            "content": [{"type": "text", "text": json.dumps(launches_data, indent=2)}],
            "isError": False,
        }

    if name == "pry_cex_listings":
        exchanges = arguments.get("exchanges") or None
        lookback_hours = int(arguments.get("lookback_hours", 24))
        try:
            from crypto_market.cex_listings import get_listing_signals
        except ImportError:
            return _crypto_module_unavailable(name)
        signals_data = await get_listing_signals(exchanges=exchanges, lookback_hours=lookback_hours)
        return {
            "content": [{"type": "text", "text": json.dumps(signals_data, indent=2)}],
            "isError": False,
        }

    if name == "pry_token_security":
        chain = arguments.get("chain", "")
        address = arguments.get("address", "")
        if not chain or not address:
            return {
                "content": [
                    {"type": "text", "text": "pry_token_security requires chain and address"}
                ],
                "isError": True,
            }
        try:
            from crypto_market.token_security import scan_token
        except ImportError:
            return _crypto_module_unavailable(name)
        scan_data = await scan_token(chain, address)
        return {
            "content": [{"type": "text", "text": json.dumps(scan_data, indent=2)}],
            "isError": False,
        }

    return None


def _marketplace_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a marketplace tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Tool {tool_name} is not available yet: the marketplace module has "
                    "not finished landing (parallel build in progress). Try again shortly."
                ),
            }
        ],
        "isError": False,
    }


async def call_marketplace_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the marketplace-intelligence MCP tools to their handlers.

    The ``marketplace`` subpackage (``amazon``, ``walmart``, ``tiktok_shop``)
    is built in parallel by other agents; every import is guarded so this
    dispatcher degrades gracefully (a readable message) if a module has not
    landed yet. Returns ``None`` for non-marketplace tools so callers fall
    through to their normal execution path (remote executor / REST proxy).
    """
    if name == "pry_amazon_product":
        asin = arguments.get("asin", "")
        if not asin:
            return {
                "content": [{"type": "text", "text": "pry_amazon_product requires asin"}],
                "isError": True,
            }
        try:
            from marketplace.amazon import get_product as get_amazon_product
        except ImportError:
            return _marketplace_module_unavailable(name)
        product_data = await get_amazon_product(asin)
        return {
            "content": [{"type": "text", "text": json.dumps(product_data, indent=2)}],
            "isError": False,
        }

    if name == "pry_amazon_search":
        query = arguments.get("query", "")
        if not query:
            return {
                "content": [{"type": "text", "text": "pry_amazon_search requires query"}],
                "isError": True,
            }
        limit = int(arguments.get("limit", 20))
        try:
            from marketplace.amazon import search_products as search_amazon_products
        except ImportError:
            return _marketplace_module_unavailable(name)
        search_data = await search_amazon_products(query, limit=limit)
        return {
            "content": [{"type": "text", "text": json.dumps(search_data, indent=2)}],
            "isError": False,
        }

    if name == "pry_walmart_product":
        product_id = arguments.get("product_id", "")
        if not product_id:
            return {
                "content": [{"type": "text", "text": "pry_walmart_product requires product_id"}],
                "isError": True,
            }
        try:
            from marketplace.walmart import get_product as get_walmart_product
        except ImportError:
            return _marketplace_module_unavailable(name)
        product_data = await get_walmart_product(product_id)
        return {
            "content": [{"type": "text", "text": json.dumps(product_data, indent=2)}],
            "isError": False,
        }

    if name == "pry_tiktok_trending":
        limit = int(arguments.get("limit", 50))
        try:
            from marketplace.tiktok_shop import get_trending
        except ImportError:
            return _marketplace_module_unavailable(name)
        trending_data = await get_trending(limit=limit)
        return {
            "content": [{"type": "text", "text": json.dumps(trending_data, indent=2)}],
            "isError": False,
        }

    return None


def _data_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a data-domain tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Tool {tool_name} is not available yet: the {package} module has "
                    "not finished landing (parallel build in progress). Try again shortly."
                ),
            }
        ],
        "isError": False,
    }


def _missing_arg(tool_name: str, arg: str) -> dict[str, Any]:
    """MCP content dict for a missing required argument."""
    return {
        "content": [{"type": "text", "text": f"{tool_name} requires {arg}"}],
        "isError": True,
    }


async def call_legal_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch legal/public-records MCP tools to their ``legal_docs`` handlers.

    The ``legal_docs`` subpackage (``dockets``, ``sec_filings``, ``sanctions``)
    is built in parallel by other agents; every import is guarded so this
    dispatcher degrades gracefully (a readable message) if a module has not
    landed yet. Returns ``None`` for non-legal tools so callers fall through.
    """
    if name == "pry_legal_dockets":
        query = arguments.get("query", "")
        if not query:
            return _missing_arg(name, "query")
        limit = int(arguments.get("limit", 20))
        try:
            from legal_docs.dockets import search_dockets
        except ImportError:
            return _data_module_unavailable(name, "legal_docs")
        data = await search_dockets(query=query, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": data, "query": query}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_legal_sec":
        ticker = arguments.get("ticker", "")
        if not ticker:
            return _missing_arg(name, "ticker")
        form_type = arguments.get("form_type", "8-K")
        limit = int(arguments.get("limit", 20))
        try:
            from legal_docs.sec_filings import search_filings
        except ImportError:
            return _data_module_unavailable(name, "legal_docs")
        data = await search_filings(ticker=ticker, form_type=form_type, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "ticker": ticker.upper()}, indent=2
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_legal_sanctions":
        screen = arguments.get("name", "")
        if not screen:
            return _missing_arg(name, "name")
        try:
            from legal_docs.sanctions import screen_name
        except ImportError:
            return _data_module_unavailable(name, "legal_docs")
        data = await screen_name(name=screen)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": data, "name": screen}, indent=2),
                }
            ],
            "isError": False,
        }

    return None


async def call_realestate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch real-estate MCP tools to their ``real_estate`` handlers (guarded)."""
    if name == "pry_realestate_search":
        location = arguments.get("location", "")
        if not location:
            return _missing_arg(name, "location")
        status = arguments.get("status", "for_sale")
        limit = int(arguments.get("limit", 20))
        try:
            from real_estate.listings import search_listings
        except ImportError:
            return _data_module_unavailable(name, "real_estate")
        data = await search_listings(location, status=status, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "location": location, "status": status},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None


async def call_jobs_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch jobs/salary MCP tools to their ``jobs`` handlers (guarded)."""
    if name == "pry_jobs_list":
        company = arguments.get("company", "")
        if not company:
            return _missing_arg(name, "company")
        board = arguments.get("board", "greenhouse")
        limit = int(arguments.get("limit", 50))
        try:
            from jobs.ats import list_jobs
        except ImportError:
            return _data_module_unavailable(name, "jobs")
        data = await list_jobs(company, board=board, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "data": data, "board": board, "company": company},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_jobs_salary":
        company = arguments.get("company", "")
        if not company:
            return _missing_arg(name, "company")
        role = arguments.get("role", "software_engineer")
        try:
            from jobs.salary import get_salary
        except ImportError:
            return _data_module_unavailable(name, "jobs")
        salary_data = await get_salary(company, role=role)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": bool(salary_data), "data": salary_data, "company": company},
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    return None


async def call_travel_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch travel MCP tools to their ``travel`` handlers (guarded)."""
    if name == "pry_flights_grid":
        origin = arguments.get("origin", "")
        dest = arguments.get("dest", "")
        start_date = arguments.get("start_date", "")
        end_date = arguments.get("end_date", "")
        if not (origin and dest and start_date and end_date):
            return _missing_arg(name, "origin/dest/start_date/end_date")
        try:
            from travel.flights import cheapest_date_grid
        except ImportError:
            return _data_module_unavailable(name, "travel")
        data = await cheapest_date_grid(origin, dest, start_date, end_date)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "data": data,
                            "origin": origin.upper(),
                            "dest": dest.upper(),
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }

    if name == "pry_hotel_rates":
        hotel_name = arguments.get("hotel_name", "")
        checkin = arguments.get("checkin", "")
        checkout = arguments.get("checkout", "")
        if not (hotel_name and checkin and checkout):
            return _missing_arg(name, "hotel_name/checkin/checkout")
        try:
            from travel.hotels import get_hotel_rates
        except ImportError:
            return _data_module_unavailable(name, "travel")
        hotel_data = await get_hotel_rates(hotel_name, checkin, checkout)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": hotel_data}, indent=2),
                }
            ],
            "isError": False,
        }

    return None


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


# Candidate public function names for the gov_data / ip_data packages. These
# packages land from parallel agents; the dispatcher resolves whichever name
# the landed module actually exposes, and reports "not available" otherwise.
_GOV_TOOL_FNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pry_procurement": (
        "gov_data",
        ("search_opportunities", "search_procurement", "list_procurement"),
    ),
    "pry_recalls": ("gov_data", ("search_recalls", "get_recalls", "list_recalls")),
}
_IP_TOOL_FNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pry_patents": ("ip_data", ("search_patents", "get_patents", "list_patents")),
    "pry_trademarks": ("ip_data", ("search_trademarks", "get_trademarks", "list_trademarks")),
}


async def _call_candidate_domain_tool(
    name: str,
    arguments: dict[str, Any],
    registry: dict[str, tuple[str, tuple[str, ...]]],
) -> dict[str, Any] | None:
    """Run a gov/ip tool via candidate function names with a guarded import."""
    entry = registry.get(name)
    if entry is None:
        return None
    package, candidates = entry
    query = arguments.get("query", "")
    if not query:
        return _missing_arg(name, "query")
    limit = int(arguments.get("limit", 20))
    try:
        mod = __import__(package, fromlist=[package])
    except ImportError:
        return _data_module_unavailable(name, package)
    fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
    if fn is None:
        return _data_module_unavailable(name, package)
    data = await fn(query, limit=limit) if _candidate_takes_limit(fn) else await fn(query)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"success": True, "data": data, "query": query}, indent=2),
            }
        ],
        "isError": False,
    }


def _candidate_takes_limit(fn: Any) -> bool:
    """Best-effort: does the gov/ip candidate accept a limit keyword?"""
    import inspect

    try:
        params = inspect.signature(fn).parameters
        return "limit" in params
    except (TypeError, ValueError):
        return True


async def call_gov_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch government-data MCP tools to their ``gov_data`` handlers (guarded)."""
    return await _call_candidate_domain_tool(name, arguments, _GOV_TOOL_FNS)


async def call_ip_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch IP-data MCP tools to their ``ip_data`` handlers (guarded)."""
    return await _call_candidate_domain_tool(name, arguments, _IP_TOOL_FNS)


# ── Sports-betting domain (parallel build, guarded) ────────────────────
# Candidate public function names for the sports_data modules. The odds /
# scores / arbitrage / ev / props modules have already landed (get_odds,
# get_scores, find_arbitrage, find_plus_ev, get_player_props); injuries and
# live_odds land from parallel agents. Each tool maps to one or more
# (module, candidate-callables) options tried in order, so the dispatcher
# resolves whichever module/function the landed code actually exposes.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_odds": (("odds", ("get_odds",)),),
    "pry_scores": (("scores", ("get_scores",)),),
    "pry_arbitrage": (("arbitrage", ("get_arbitrage", "find_arbitrage", "scan_arbitrage")),),
    "pry_plus_ev": (
        ("ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
        ("plus_ev", ("get_plus_ev", "find_plus_ev", "scan_plus_ev")),
    ),
    "pry_props": (("props", ("get_player_props", "get_props", "search_props", "player_props")),),
    "pry_injuries": (("injuries", ("get_injuries", "list_injuries", "injury_report")),),
    "pry_live_odds": (
        ("live", ("get_live_odds", "live_odds")),
        ("live_odds", ("get_live_odds", "live_odds")),
    ),
}


def _sports_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a sports tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Tool {tool_name} is not available yet: the sports_data module has "
                    "not finished landing (parallel build in progress). Try again shortly."
                ),
            }
        ],
        "isError": False,
    }


def _sports_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for a sports tool from MCP arguments.

    The declared schema (sport/market/book/... ) is richer than what some
    landed modules accept today; kwargs the callable does not support are
    filtered out by the dispatcher (``_callable_accepts``) so the call never
    fails on an unknown keyword.
    """
    if name == "pry_odds":
        kwargs = {
            "event_query": arguments.get("event_query", ""),
            "sport": arguments.get("sport", "all"),
            "limit": int(arguments.get("limit", 20)),
        }
        # Only forward market/book when the caller actually set them — the
        # landed get_odds defaults (market="h2h", book=None) are safer than
        # empty strings (book="" would normalize to "unknown").
        if arguments.get("market"):
            kwargs["market"] = arguments["market"]
        if arguments.get("book"):
            kwargs["book"] = arguments["book"]
        return kwargs
    if name == "pry_scores":
        return {"sport": arguments.get("sport", "all"), "date": arguments.get("date", "today")}
    if name == "pry_arbitrage":
        return {
            "sport": arguments.get("sport", "all"),
            "min_yield_pct": float(arguments.get("min_yield_pct", 0.5)),
        }
    if name == "pry_plus_ev":
        return {
            "sharp_book": arguments.get("sharp_book", "pinnacle"),
            "min_ev_pct": float(arguments.get("min_ev_pct", 1.0)),
        }
    if name == "pry_props":
        return {
            "player": arguments.get("player", ""),
            "sport": arguments.get("sport", "all"),
            "market": arguments.get("market", ""),
        }
    if name == "pry_injuries":
        return {"sport": arguments.get("sport", "all"), "team": arguments.get("team", "all")}
    if name == "pry_live_odds":
        return {"sport": arguments.get("sport", "all"), "limit": int(arguments.get("limit", 20))}
    return dict(arguments)


def _callable_accepts(fn: Any, kwarg: str) -> bool:
    """Best-effort: does the callable accept a keyword argument?"""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    return kwarg in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


async def call_sports_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch sports-betting MCP tools to their ``sports_data`` handlers (guarded).

    The ``sports_data`` subpackage (odds, scores, arbitrage, plus_ev, props,
    injuries, live_odds) is built in parallel by other agents; every import is
    guarded so this dispatcher degrades gracefully (a readable message) if a
    module has not landed yet. Returns ``None`` for non-sports tools so callers
    fall through to their normal execution path (remote executor / REST proxy).
    """
    entry = _SPORTS_TOOL_FNS.get(name)
    if entry is None:
        return None
    for module_name, candidates in entry:
        try:
            mod = __import__(f"sports_data.{module_name}", fromlist=[module_name])
        except ImportError:
            continue
        fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
        if fn is None:
            continue
        kwargs = _sports_tool_kwargs(name, arguments)
        data = await fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": data}, indent=2),
                }
            ],
            "isError": False,
        }
    return _sports_module_unavailable(name)
