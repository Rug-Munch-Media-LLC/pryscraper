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

PRY_TOOLS = [
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
            "Use to collect an entire docs site, blog, or directory, e.g. every page under "
            "/docs/ or all blog posts up to 50 pages deep."
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
    },
    {
        "name": "pry_search_templates",
        "description": (
            "Search all 110+ scraper templates by keyword, category, or site name. "
            "Use before pry_template to find the right template, e.g. 'amazon', 'jobs', "
            "or 'real estate'."
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
    },
    {
        "name": "pry_screenshot",
        "description": (
            "Take a full-page screenshot of a URL and return it as a base64-encoded PNG. "
            "Use for visual verification or design QA of a rendered page, e.g. capture a "
            "checkout flow to confirm the layout before launch."
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
]


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
