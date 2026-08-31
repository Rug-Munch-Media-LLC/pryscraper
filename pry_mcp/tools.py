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
            "Compliance intelligence in two modes: pass a URL to check whether scraping it "
            "is legally safe (robots.txt, ToS, GDPR/CCPA, PII exposure -> green/yellow/red "
            "risk score with recommendations), or pass query/agency to search regulatory "
            "compliance records — enforcement actions, fines, sanctions, and watchlist "
            "entries, e.g. query='Binance' for its regulatory history. "
            "Use before scraping an uncertain site or when screening a company for "
            "compliance exposure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "The URL to run a legal compliance check on, e.g. https://example.com "
                        "(legacy URL-check mode — omit when using query/agency)"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Regulatory compliance search query (company, entity, or topic), "
                        "e.g. 'Binance' or 'crypto exchange fines'"
                    ),
                },
                "agency": {
                    "type": "string",
                    "description": (
                        "Optional regulator / agency filter for the compliance search, "
                        "e.g. 'SEC', 'FTC', 'CFTC', 'OFAC'"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of compliance records to return (default: 20)",
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
                        "url": {"type": "string"},
                        "risk_level": {
                            "type": "string",
                            "enum": ["green", "yellow", "red"],
                        },
                        "risk_score": {"type": "number"},
                        "checks": {"type": "array", "items": {"type": "object"}},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                        "query": {"type": "string"},
                        "agency": {"type": "string"},
                        "records": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string"},
                                    "title": {"type": "string"},
                                    "agency": {"type": "string"},
                                    "date": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "source": {"type": "string"},
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
        "name": "pry_balance",
        "description": (
            "Read the prepaid balance of a Pry account (bulk scrape credits purchased via "
            "crypto). Pass your pry API key (e.g. api_key='pry_abc123_deadbeef...') or a "
            "user_id to see the USD balance + low-balance flag. Use before buying a pack to "
            "confirm you can afford an operation, or after a purchase to confirm the credit "
            "landed (e.g. after a 5000-credit starter pack you should see ~5.00 USD). This is "
            "a free read of your own account — it does not spend credits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "description": "The pry API key whose owner's balance to read.",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional explicit account id (takes precedence over api_key).",
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
                        "balance": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"},
                                "balance_usd": {"type": "number"},
                                "low_balance": {"type": "boolean"},
                            },
                        }
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_buy_pack",
        "description": (
            "Initiate a crypto purchase of a bulk scrape-credit pack. Pass a pack id "
            "(e.g. pack_id='starter' for $5/5,000 credits) and it returns a spec-compliant "
            "x402 PaymentRequired manifest with the real receiving wallet as payToAddress and "
            "the server-authoritative price in atomic units. The agent/partner pays USDC "
            "on-chain (or the quoted asset, defaults to the configured network), then calls the "
            "confirm endpoint with the tx hash to credit the balance — and on first purchase an "
            "API key is minted. An empty payToAddress in the response means the operator hasn't "
            "configured a receiving wallet; never pay a placeholder address."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_id": {
                    "type": "string",
                    "default": "starter",
                    "description": "Credit-pack id: starter ($5/5,000 credits), growth ($20/20,000), bulk ($100/100,000).",
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional API key whose owner receives the credits (else a key is minted on purchase).",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional explicit account id to credit.",
                },
                "network": {
                    "type": "string",
                    "description": "Optional CAIP-2 / legacy x402 network (defaults to the configured default).",
                },
                "asset": {
                    "type": "string",
                    "default": "USDC",
                    "description": "Optional asset to pay in (defaults to USDC).",
                },
            },
            "required": ["pack_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "status_code": {"type": "integer"},
                        "payment_required": {"type": "object"},
                        "invoice_id": {"type": "string"},
                        "pack_id": {"type": "string"},
                        "amount_usd": {"type": "number"},
                        "amount_atomic": {"type": "integer"},
                        "credits": {"type": "integer"},
                        "chain": {"type": "string"},
                        "pay_to": {"type": "string"},
                        "asset": {"type": "string"},
                        "expires_at": {"type": "string"},
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
        "name": "pry_kol_leaderboards",
        "description": (
            "Scrape KOL / crypto-influencer leaderboards for usernames (handles), "
            "wallets, followers and P&L / win-loss stats. Reads public trader "
            "leaderboards (kolscan.io Solana trader board; gmgn.ai and dexscreener "
            "smart-money boards are registered but Cloudflare/JS-gated and flagged "
            "[REVIEW]). Use to grow a KOL watchlist, e.g. 'pull the top KOL wallets "
            "from the kolscan leaderboard' or 'find new crypto influencer handles + wallets'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 500,
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum number of KOL records to return (default: 500)",
                },
                "source": {
                    "type": "string",
                    "enum": [
                        "kolscan_leaderboard",
                        "gmgn_smart_money",
                        "dexscreener_smart_money",
                        "all",
                    ],
                    "default": "kolscan_leaderboard",
                    "description": (
                        "Which KOL source to scrape. Blocked sources return a 'blocked' "
                        "annotation (no rows) until a JS-capable solver is wired in."
                    ),
                },
                "health_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, only return per-source reachability/block health.",
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
                        "records": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "handle": {"type": "string"},
                                    "name": {"type": "string"},
                                    "address": {"type": "string"},
                                    "chain": {"type": "string"},
                                    "source": {"type": "string"},
                                    "twitter": {"type": "string"},
                                    "profit": {"type": "number"},
                                    "wins": {"type": "integer"},
                                    "losses": {"type": "integer"},
                                    "followers": {"type": "integer"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "blocked": {"type": "array"},
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
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of dockets to skip before the page (pagination)",
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
    {
        "name": "pry_historical_odds",
        "description": (
            "Get historical betting odds for past events from The Odds API "
            "history feed: the closing lines, opening lines, and best available "
            "prices for moneyline, spreads, and totals on a given date. "
            "Use to backtest betting models or audit how lines moved, e.g. "
            "'what were the closing NFL moneylines on 20260810?' or call with "
            "sport='nba' and date='2026-08-01' for that day's historical slate."
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
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of historical records (default: 20)",
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
                            "date": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_betting_percentages",
        "description": (
            "Get public betting percentages (the share of bets and the share of "
            "money on each side of a game) across bookmakers, e.g. 'how much of "
            "the money is on the Chiefs tonight?' or call with sport='nfl' to see "
            "the whole slate. Use to spot sharp-side steam and contrarian plays "
            "where the public leans one way but the line is not moving."
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
                "event": {
                    "type": "string",
                    "description": "Event substring filter, e.g. 'Chiefs vs Bills'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of percentage records (default: 20)",
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
                            "home_bets_pct": {"type": "number"},
                            "away_bets_pct": {"type": "number"},
                            "home_money_pct": {"type": "number"},
                            "away_money_pct": {"type": "number"},
                            "bookmaker": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_sharp_consensus",
        "description": (
            "Get the sharp consensus: the closing-line value and consensus price "
            "from sharp books (Pinnacle, Circa, BetOnline) for the biggest games. "
            "Use to identify where professional money is, e.g. 'what is the sharp "
            "consensus on the Packers game?' or call with sport='nba' for the "
            "sharpest lines across tonight's slate."
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
                "sharp_books": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Sharp books to aggregate (e.g., ['pinnacle', 'circa']); "
                        "defaults to the configured sharp list"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of consensus records (default: 20)",
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
                            "consensus_price": {"type": "number"},
                            "clv_pct": {"type": "number"},
                            "books": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_alerts",
        "description": (
            "Get or manage money-printer alerts: significant line moves, sharp "
            "steam, limit-up CLV, and bettor-facing notifications you subscribe "
            "to. Use to stay on top of the market without polling, e.g. 'what "
            "alerts are active right now?' or call with alert_type='line_move' "
            "to list the biggest recent line moves across all sports."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "alert_type": {
                    "type": "string",
                    "default": "",
                    "description": (
                        "Alert category filter: 'line_move', 'steam', 'clv', "
                        "'injury', or empty for all"
                    ),
                },
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
                    "description": "Maximum number of alerts (default: 20)",
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
                            "alert_type": {"type": "string"},
                            "sport": {"type": "string"},
                            "event": {"type": "string"},
                            "message": {"type": "string"},
                            "severity": {"type": "string"},
                            "created_at": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_books",
        "description": (
            "Aggregate live odds for one sport/market across all 112 sportsbooks "
            "in Pry's registry (US, offshore, EU, UK, and Asian books) by "
            "scraping each book directly through Pry's intelligent fallback "
            "chain — no paid odds API, no API keys. "
            "Use to find the best price anywhere for a slate, e.g. call with "
            "sport='nba' and market='h2h' to see every reachable book's "
            "moneyline for tonight's games, or pass market='spreads' to sweep "
            "the point-spread market across the whole registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": (
                        "Sport key to aggregate (e.g. 'nba', 'nfl', 'mlb', 'nhl', "
                        "'epl'); books are scraped per-sport (default: nba)"
                    ),
                },
                "market": {
                    "type": "string",
                    "default": "h2h",
                    "description": (
                        "Betting market (e.g., 'h2h' moneyline, 'spreads', "
                        "'totals'); default is h2h moneyline"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of odds records to return (default: 50)",
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
                            "market": {"type": "string"},
                            "book": {"type": "string"},
                            "book_id": {"type": "string"},
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "home_odds": {"type": "number"},
                            "away_odds": {"type": "number"},
                            "source": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
                "market": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_book_coverage",
        "description": (
            "Get sportsbook coverage-registry statistics: how many of the 112 "
            "sportsbooks Pry scrapes directly, broken down by category (US, "
            "offshore, EU, UK, Asian), extraction method, and geo-requirement. "
            "Use to verify the breadth of the no-paid-API odds network before "
            "relying on it, e.g. 'how many US books do you cover?' or to confirm "
            "the 112-book total and the per-category split in one call."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "total": {"type": "integer"},
                        "by_category": {"type": "object"},
                        "by_method": {"type": "object"},
                        "geo_required": {"type": "object"},
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "methods": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
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
    {
        "name": "pry_weather",
        "description": (
            "Get current weather and short-range forecasts for a location, built "
            "for research pipelines that need environmental context (rain, wind, "
            "temperature, AQI) alongside other data. "
            "Use to enrich scraping jobs or model outdoor conditions, e.g. "
            "'what is the weather in Austin, TX right now?' or call with "
            "latitude/longitude to avoid geocoding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or place query, e.g. 'Austin, TX'",
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude (alternative to location)",
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude (alternative to location)",
                },
                "forecast_days": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 0,
                    "maximum": 16,
                    "description": "Days of forecast to include (0 = current only)",
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
                        "location": {"type": "string"},
                        "temperature_c": {"type": "number"},
                        "condition": {"type": "string"},
                        "humidity_pct": {"type": "number"},
                        "wind_kph": {"type": "number"},
                        "forecast": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_agri",
        "description": (
            "Get agricultural data: crop conditions, growing-degree days, soil "
            "moisture, and commodity-relevant climate indices for a region. "
            "Use to model crop yield risk or monitor growing regions, e.g. "
            "'what are the corn growing conditions in Iowa?' or call with "
            "region='us' and crop='corn' for the USDA-style condition report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "default": "us",
                    "description": "Region code, e.g. 'us', 'br', 'in' (default: 'us')",
                },
                "crop": {
                    "type": "string",
                    "default": "",
                    "description": "Crop filter, e.g. 'corn', 'soybeans', 'wheat'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of records (default: 20)",
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
                            "region": {"type": "string"},
                            "crop": {"type": "string"},
                            "condition": {"type": "string"},
                            "gdd": {"type": "number"},
                            "soil_moisture_pct": {"type": "number"},
                            "date": {"type": "string"},
                        },
                    },
                },
                "region": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_papers",
        "description": (
            "Search academic papers and preprints (arXiv, Semantic Scholar, "
            "PubMed) by keyword, author, or topic and return titles, abstracts, "
            "and citation counts. "
            "Use for research pipelines that need scholarly grounding, e.g. "
            "'find recent papers on retrieval-augmented generation' or call with "
            "author='Smith' and limit=10 for recent works."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'retrieval augmented generation'",
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author name, e.g. 'Smith'",
                },
                "year_from": {
                    "type": "integer",
                    "description": "Earliest publication year, e.g. 2020",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of papers (default: 20)",
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
                            "title": {"type": "string"},
                            "authors": {"type": "array", "items": {"type": "string"}},
                            "abstract": {"type": "string"},
                            "year": {"type": "integer"},
                            "citations": {"type": "integer"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_domain",
        "description": (
            "Get a domain intelligence report: WHOIS registration, SSL/TLS "
            "details, hosting provider, and technology fingerprint for a "
            "website. "
            "Use to enrich leads, vet domains before scraping, or map a "
            "competitor's stack, e.g. 'what can you tell me about example.com?' "
            "or call with domain='rugmunch.io' for hosting and tech details."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain to analyze, e.g. 'example.com'",
                },
                "include_tech": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include technology fingerprint (default: true)",
                },
            },
            "required": ["domain"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "registrar": {"type": "string"},
                        "registered_at": {"type": "string"},
                        "expires_at": {"type": "string"},
                        "hosting_provider": {"type": "string"},
                        "tech_stack": {"type": "array", "items": {"type": "string"}},
                        "ssl_issuer": {"type": "string"},
                    },
                },
                "domain": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_events",
        "description": (
            "Search live event listings (concerts, sports, theater) by keyword "
            "and optionally location or date, backed by Ticketmaster / SeatGeek "
            "class feeds. Use to find upcoming events for an artist or venue, "
            "e.g. 'what concerts are near Austin next month?' or call with "
            "query='Taylor Swift' and location='New York' for dated listings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Event keyword search, e.g. 'Taylor Swift' or 'Broadway'",
                },
                "location": {
                    "type": "string",
                    "description": "City / region filter, e.g. 'New York' (optional)",
                },
                "date": {
                    "type": "string",
                    "description": "Date filter YYYY-MM-DD (optional)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum number of events (default: 20)",
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
                            "event_id": {"type": "string"},
                            "name": {"type": "string"},
                            "venue": {"type": "string"},
                            "city": {"type": "string"},
                            "date": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_resale",
        "description": (
            "Get resale ticket pricing for a specific event: asking prices, "
            "ticket counts, and section-level ranges across resale "
            "marketplaces. Use with an event_id from pry_events to size demand "
            "before buying, e.g. call with event_id from a sold-out concert to "
            "see floor and nosebleed asking ranges side by side."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event identifier from pry_events, e.g. 'vv1aZt7B8v'",
                },
            },
            "required": ["event_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "min_price": {"type": "number"},
                        "max_price": {"type": "number"},
                        "ticket_count": {"type": "integer"},
                        "sections": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_freight",
        "description": (
            "Get ocean container freight rates for a route: spot and contract "
            "rates per 40ft container across major trade lanes, plus FMC "
            "contract visibility where available. Use to model shipping costs, "
            "e.g. 'container rates from Shanghai to Los Angeles this week', or "
            "call with route='Far East to US West Coast' for the lane spread."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "description": (
                        "Trade lane, e.g. 'Shanghai to Los Angeles' or 'Far East to US West Coast'"
                    ),
                },
                "origin": {
                    "type": "string",
                    "description": "Origin port or region (alternative to route)",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination port or region (alternative to route)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of rate quotes (default: 20)",
                },
            },
            "required": ["route"],
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
                            "route": {"type": "string"},
                            "container_type": {"type": "string"},
                            "rate_usd": {"type": "number"},
                            "valid_from": {"type": "string"},
                            "valid_to": {"type": "string"},
                        },
                    },
                },
                "route": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_energy_lmp",
        "description": (
            "Get electricity locational marginal prices (LMP) for an ISO region "
            "and date, with day-ahead / real-time splits where available. Use "
            "to model energy costs or spot volatility, e.g. 'LMP for ERCOT "
            "today', or call with region='PJM' and date='2026-08-16' for nodal "
            "pricing snapshots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": (
                        "ISO / balancing authority, e.g. 'ERCOT', 'PJM', 'CAISO', 'NYISO'"
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD (default: today)",
                },
            },
            "required": ["region"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"},
                        "date": {"type": "string"},
                        "lmp_usd_mwh": {"type": "number"},
                        "day_ahead_usd_mwh": {"type": "number"},
                        "real_time_usd_mwh": {"type": "number"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_grocery",
        "description": (
            "Get grocery prices for a product or category, optionally filtered "
            "by ZIP code for local store pricing. Use to compare staple costs "
            "across markets, e.g. 'price of a dozen eggs in 10001', or call "
            "with query='milk' and zip='78701' to see regional averages and "
            "store-level ranges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Item or category, e.g. 'eggs', 'milk', 'avocados'",
                },
                "zip": {
                    "type": "string",
                    "description": "5-digit ZIP code for local pricing (optional)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of price records (default: 20)",
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
                            "item": {"type": "string"},
                            "price_usd": {"type": "number"},
                            "unit": {"type": "string"},
                            "store": {"type": "string"},
                            "zip": {"type": "string"},
                            "date": {"type": "string"},
                        },
                    },
                },
                "query": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_restaurant",
        "description": (
            "Get a restaurant's menu with prices: items, sections, and per-dish "
            "pricing for a named restaurant. Use to build cost-of-dining "
            "datasets or research competitors, e.g. call with "
            "name=\"Katz's Delicatessen\" and location='New York' for the full "
            "menu with prices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": 'Restaurant name, e.g. "Katz\'s Delicatessen"',
                },
                "location": {
                    "type": "string",
                    "description": "City / address to disambiguate (optional)",
                },
            },
            "required": ["name"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "cuisine": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "section": {"type": "string"},
                                    "items": {"type": "array", "items": {"type": "object"}},
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
        "name": "pry_imports",
        "description": (
            "Get U.S. customs import records for a company: shipment dates, "
            "commodity descriptions, suppliers, and origin countries. Use to "
            "size a competitor's supply chain or vet suppliers, e.g. call with "
            "company='Tesla Inc' for recent bill-of-lading entries with "
            "quantities."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name or importer-of-record, e.g. 'Tesla Inc'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of shipment records (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of shipment records to skip before the page (pagination)",
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
                            "consignee": {"type": "string"},
                            "supplier": {"type": "string"},
                            "commodity": {"type": "string"},
                            "origin_country": {"type": "string"},
                            "arrival_date": {"type": "string"},
                            "value_usd": {"type": "number"},
                        },
                    },
                },
                "company": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_firmographics",
        "description": (
            "Get firmographic data for a company: employee count band, revenue "
            "range, founding year, headquarters, industry, and company type. "
            "Use to segment leads or enrich CRM records, e.g. call with "
            "company='Rug Munch Media' for the standard firmographic profile "
            "with confidence scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name, e.g. 'Rug Munch Media'",
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
                        "employees_band": {"type": "string"},
                        "revenue_range_usd": {"type": "string"},
                        "founded_year": {"type": "integer"},
                        "headquarters": {"type": "string"},
                        "industry": {"type": "string"},
                        "company_type": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
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
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "app_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "rating": {"type": "number"},
                                    "categories": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
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
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "app_id": {"type": "string"},
                                    "rating": {"type": "integer"},
                                    "title": {"type": "string"},
                                    "body": {"type": "string"},
                                    "author": {"type": "string"},
                                    "date": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "app_id": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
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
    {
        "name": "pry_company_watch",
        "description": (
            "Return the regulatory watch record for a company — recent enforcement "
            "actions, fines, sanctions, and compliance filings — e.g. company='OpenAI' "
            "for its compliance exposure. "
            "Use for due diligence, vendor screening, or competitor risk monitoring "
            "before partnering or trading. Backed by free public regulatory feeds; "
            "degrades to an empty record when no data is found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name to watch, e.g. 'OpenAI'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of watch records to return (default: 20)",
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
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string"},
                                    "title": {"type": "string"},
                                    "date": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "source": {"type": "string"},
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
        "name": "pry_deals",
        "description": (
            "Search deals, discounts, and promotions by keyword across public deal feeds, "
            "returning merchant, product, price, discount percentage, and expiry for each "
            "result. "
            "Use to build deal trackers, power shopping comparisons, or feed coupon "
            "content, e.g. query='PS5' for current console offers. Best-effort over free "
            "public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Deal search keywords, e.g. 'PS5'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of deals to return (default: 20)",
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
                                    "merchant": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "discount_pct": {"type": "number"},
                                    "expires_at": {"type": "string"},
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
        "name": "pry_drop_alert",
        "description": (
            "Check for drop alerts / limited product restock or flash-sale signals for a "
            "product, returning availability windows, price drops, and the merchant for "
            "each signal, e.g. product='RTX 5090' to track GPU drops. "
            "Use to power restock-notification bots, supply monitoring, or scalper-"
            "resistant buying queues. Best-effort over public feeds; degrades to an "
            "empty list when no drop signal is found."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Product name or SKU to watch for drops, e.g. 'RTX 5090'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of drop signals to return (default: 20)",
                },
            },
            "required": ["product"],
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
                                    "product": {"type": "string"},
                                    "merchant": {"type": "string"},
                                    "price": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "availability": {"type": "string"},
                                    "alert_type": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "product": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_contracts",
        "description": (
            "Search government contract opportunities and awards by keyword across "
            "public procurement feeds, returning agency, solicitation number, award "
            "value, status, and deadline for each result. "
            "Use to monitor public-sector RFPs and awarded contracts, e.g. "
            "query='cybersecurity' for current federal bidding data. Best-effort over "
            "free public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Contract search keywords, e.g. 'cybersecurity'",
                },
                "agency": {
                    "type": "string",
                    "description": "Optional agency filter, e.g. 'DHS'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of contracts to return (default: 20)",
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
                                    "agency": {"type": "string"},
                                    "solicitation_number": {"type": "string"},
                                    "value": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "status": {"type": "string"},
                                    "deadline": {"type": "string"},
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
        "name": "pry_grants",
        "description": (
            "Search government grant opportunities by keyword across public grant "
            "feeds, returning agency, opportunity number, funding amount, eligibility, "
            "and deadline for each result. "
            "Use to find open funding programs for research, nonprofits, or "
            "businesses, e.g. query='small business innovation research'. Best-effort "
            "over free public sources; never raises and returns an empty list on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Grant search keywords, e.g. 'small business innovation research'",
                },
                "agency": {
                    "type": "string",
                    "description": "Optional agency filter, e.g. 'NSF'",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of grants to return (default: 20)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of grants to skip before the page (pagination)",
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
                                    "agency": {"type": "string"},
                                    "opportunity_number": {"type": "string"},
                                    "amount": {"type": "number"},
                                    "currency": {"type": "string"},
                                    "eligibility": {"type": "string"},
                                    "deadline": {"type": "string"},
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
        "name": "pry_actor_catalog",
        "description": (
            "List every Pry Apify Store actor (94) with description, category, pricing "
            "events and per-event USD price. Store parity surface: anything "
            "runnable on Apify is discoverable here. Filter by optional "
            "'domain' substring (e.g. 'monitor', 'crypto', 'seo'). Supports "
            "offset/limit pagination over the full catalog."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional case-insensitive substring filter over actor name/title.",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of actors to skip before the page (pagination)",
                },
                "limit": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Maximum actors per page (0 = all)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "total": {"type": "integer"},
                "count": {"type": "integer", "description": "Actors on this page"},
                "actors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "actor": {"type": "string"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "category": {"type": "string"},
                            "icon": {"type": "string"},
                            "icon_hd": {"type": "string"},
                            "processor": {"type": ["string", "null"]},
                            "uses_browser": {"type": "boolean"},
                            "min_memory_mbytes": {"type": "integer"},
                            "pricing_events": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "event": {"type": "string"},
                                        "title": {"type": "string"},
                                        "price_usd": {"type": "number"},
                                    },
                                    "required": ["event", "price_usd"],
                                },
                            },
                        },
                        "required": ["actor", "title", "category", "pricing_events"],
                    },
                },
            },
            "required": ["success", "total", "actors"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "pry_actor_run",
        "description": (
            "Run any Pry Apify actor's pipeline locally over URLs - same "
            "PPEScraperRunner + processor code path as the deployed store "
            "actors. Use after pry_actor_catalog: pass the actor name plus "
            "target urls; results are the same dataset items the Apify run "
            "would produce. x402 pay-per-call: each processed URL bills the "
            "actor's first PPE pricing event (see pry_actor_catalog / "
            "pry_x402_pricing for per-event USD prices). Examples: actor='news-feed-monitor', "
            "actor='universal-scraper', actor='token-safety-scanner'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor": {
                    "type": "string",
                    "description": "Actor name without the pry- prefix, e.g. 'news-feed-monitor'.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri"},
                    "description": "Target URLs for the actor pipeline.",
                },
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                    "description": "Hard cap on processed URLs (runaway protection).",
                },
            },
            "required": ["actor", "urls"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "actor": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "status": {"type": "string"},
                            "method": {"type": "string"},
                            "content": {"type": "string"},
                            "scraped_at": {"type": "string"},
                            "error": {"type": "string"},
                        },
                    },
                    "description": "Dataset items, same shape as the Apify actor run",
                },
                "item_count": {"type": "integer"},
                "format": {
                    "type": "string",
                    "description": "Output format used for item content (default: markdown)",
                },
                "equivalent_apify_charge_usd": {
                    "type": "number",
                    "description": "PPE charge the equivalent Apify run would bill",
                },
                "note": {"type": "string"},
            },
            "required": ["success", "actor", "items", "item_count"],
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
# Audit (2026-08-17, all 73 PRY_TOOLS):
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
#   * The 4 new money-printer sports tools (pry_historical_odds,
#     pry_betting_percentages, pry_sharp_consensus, pry_alerts) are pure
#     reads of odds/history/consensus feeds — same default annotations.
#   * The 4 new coverage tools (pry_books, pry_book_coverage,
#     pry_scrape_methods, pry_all_sources) are pure reads of the 112-book
#     sportsbook registry / multi-source odds feeds — same default
#     read-only, non-destructive, idempotent annotations.
#   * The climate/research tools (pry_weather, pry_agri, pry_papers,
#     pry_domain) are pure reads of public weather/academic/WHOIS feeds —
#     same default read-only, non-destructive, idempotent annotations.
#   * The 8 new events/freight/energy/food/supply tools (pry_events,
#     pry_resale, pry_freight, pry_energy_lmp, pry_grocery, pry_restaurant,
#     pry_imports, pry_firmographics) are pure reads of public ticket /
#     freight / energy / retail / customs feeds — same default annotations.
#   * The 2 new bidding tools (pry_contracts, pry_grants) are pure reads of
#     public government procurement / grant feeds — same default read-only,
#     non-destructive, idempotent annotations.
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
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the crypto_market module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
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
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": launches_data}, indent=2),
                }
            ],
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
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": signals_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_token_security":
        chain = arguments.get("chain", "")
        address = arguments.get("address", "")
        if not chain or not address:
            return _missing_arg(name, "chain and address")
        try:
            from crypto_market.token_security import scan_token
        except ImportError:
            return _crypto_module_unavailable(name)
        scan_data = await scan_token(chain, address)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": scan_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_kol_leaderboards":
        source = arguments.get("source", "kolscan_leaderboard")
        limit = int(arguments.get("limit", 500))
        health_only = bool(arguments.get("health_only", False))
        try:
            from crypto_market.kol_leaderboards import fetch_kol_leaderboards
        except ImportError:
            return _crypto_module_unavailable(name)
        if health_only:
            try:
                from crypto_market.kol_leaderboards import source_health
            except ImportError:
                return _crypto_module_unavailable(name)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"success": True, "data": source_health()}, indent=2),
                    }
                ],
                "isError": False,
            }
        sources = None if source == "all" else [source]
        result = await fetch_kol_leaderboards(limit=limit, sources=sources)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": result}, indent=2),
                }
            ],
            "isError": False,
        }

    return None


def _marketplace_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a marketplace tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the marketplace module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
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
            return _missing_arg(name, "asin")
        try:
            from pry.commerce.marketplace.amazon import get_product as get_amazon_product
        except ImportError:
            return _marketplace_module_unavailable(name)
        product_data = await get_amazon_product(asin)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": product_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_amazon_search":
        query = arguments.get("query", "")
        if not query:
            return _missing_arg(name, "query")
        limit = int(arguments.get("limit", 20))
        try:
            from pry.commerce.marketplace.amazon import search_products as search_amazon_products
        except ImportError:
            return _marketplace_module_unavailable(name)
        search_data = await search_amazon_products(query, limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": search_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_walmart_product":
        product_id = arguments.get("product_id", "")
        if not product_id:
            return _missing_arg(name, "product_id")
        try:
            from pry.commerce.marketplace.walmart import get_product as get_walmart_product
        except ImportError:
            return _marketplace_module_unavailable(name)
        product_data = await get_walmart_product(product_id)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": product_data}, indent=2),
                }
            ],
            "isError": False,
        }

    if name == "pry_tiktok_trending":
        limit = int(arguments.get("limit", 50))
        try:
            from pry.commerce.marketplace.tiktok_shop import get_trending
        except ImportError:
            return _marketplace_module_unavailable(name)
        trending_data = await get_trending(limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"success": True, "data": trending_data}, indent=2),
                }
            ],
            "isError": False,
        }

    return None


def _data_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a data-domain tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the {package} module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _missing_arg(tool_name: str, arg: str) -> dict[str, Any]:
    """MCP content dict for a missing required argument (structured error)."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": f"{tool_name} requires {arg}",
                        "code": "MISSING_ARGUMENT",
                    }
                ),
            }
        ],
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
        try:
            offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        # Over-fetch by offset so the slice still yields a full page.
        data = await search_dockets(query=query, limit=limit + offset)
        data, total = _apply_offset(data, arguments)
        payload: dict[str, Any] = {"success": True, "data": data, "query": query}
        if total:
            payload["total"] = total
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2),
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
    # Money-printer tools land from parallel agents (historical_odds,
    # betting_percentages, sharp_consensus, alerts). Each maps to one or more
    # (module, candidate-callables) options so the landed module/function name
    # is resolved defensively, mirroring the arbitrage/plus_ev pattern.
    "pry_historical_odds": (
        ("historical", ("get_historical_odds", "historical_odds", "get_historical")),
        ("historical_odds", ("get_historical_odds", "historical_odds", "get_historical")),
    ),
    "pry_betting_percentages": (
        (
            "betting_percentages",
            ("get_betting_percentages", "betting_percentages", "get_percentages"),
        ),
        ("percentages", ("get_betting_percentages", "betting_percentages", "get_percentages")),
    ),
    "pry_sharp_consensus": (
        ("sharp_consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
        ("consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
    ),
    "pry_alerts": (
        ("alerts", ("list_alerts", "get_alerts", "alerts")),
        ("alert", ("list_alerts", "get_alerts", "alerts")),
    ),
    # Expanded sportsbook coverage (landed from parallel agents): the 112-book
    # registry scraper (books.py) and the multi-source odds aggregator (odds.py).
    # books.get_all_books_odds is async; books.books_coverage is sync (the
    # dispatcher below handles both). pry_scrape_methods reads the
    # scraping_methods.METHODS registry (fallback-chain tiers) and is
    # special-cased in call_sports_tool.
    "pry_books": (("books", ("get_all_books_odds",)),),
    "pry_book_coverage": (("books", ("books_coverage",)),),
    "pry_scrape_methods": (("scraping_methods", ("METHODS",)),),
    "pry_all_sources": (("odds", ("get_odds_multi",)),),
}


def _sports_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a sports tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the sports_data module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
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
    if name == "pry_historical_odds":
        kwargs = {
            "sport": arguments.get("sport", "all"),
            "date": arguments.get("date", "today"),
            "limit": int(arguments.get("limit", 20)),
        }
        # The landed historical module keys off the Odds API event id.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        elif arguments.get("event_query"):
            kwargs["event_id"] = arguments["event_query"]
        return kwargs
    if name == "pry_betting_percentages":
        kwargs = {"sport": arguments.get("sport", "all")}
        # The landed percentages module is event-id centric.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        elif arguments.get("event"):
            kwargs["event_id"] = arguments["event"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_sharp_consensus":
        kwargs = {"sport": arguments.get("sport", "all")}
        # The landed consensus module is event-id centric.
        if arguments.get("event_id"):
            kwargs["event_id"] = arguments["event_id"]
        if arguments.get("sharp_books"):
            kwargs["books"] = arguments["sharp_books"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_alerts":
        kwargs = {"sport": arguments.get("sport", "all")}
        if arguments.get("alert_type"):
            kwargs["alert_type"] = arguments["alert_type"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_books":
        kwargs = {
            "sport": arguments.get("sport", "nba"),
            "market": arguments.get("market", "h2h"),
            "limit": int(arguments.get("limit", 50)),
        }
        return kwargs
    if name == "pry_book_coverage":
        return {}
    if name == "pry_scrape_methods":
        return {}
    if name == "pry_all_sources":
        kwargs = {
            "event_id": arguments.get("event_id", ""),
            "market": arguments.get("market", "h2h"),
            "limit": int(arguments.get("limit", 50)),
            "sources": arguments.get("sources", "all"),
        }
        if arguments.get("book"):
            kwargs["book"] = arguments["book"]
        return kwargs
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
    injuries, live_odds, books) is built in parallel by other agents; every
    import is guarded so this dispatcher degrades gracefully (a readable
    message) if a module has not landed yet. Returns ``None`` for non-sports
    tools so callers fall through to their normal execution path (remote
    executor / REST proxy).
    """
    entry = _SPORTS_TOOL_FNS.get(name)
    if entry is None:
        return None
    # pry_scrape_methods reads the METHODS registries (dicts/tuples of method
    # metadata, not callables) — resolve them directly instead of trying to
    # call them. Primary source is the top-level scraping_methods module
    # (fallback-chain tiers); the sports_data.books extraction vocabulary is
    # the fallback.
    if name == "pry_scrape_methods":
        try:
            mod = __import__("scraping_methods", fromlist=["METHODS"])
            registry = getattr(mod, "METHODS", {})
            if isinstance(registry, dict):
                methods = [
                    {
                        "key": key,
                        "name": str(meta.get("name", key)),
                        "sync": bool(meta.get("sync", False)),
                        "cost": str(meta.get("cost", "")),
                        "when": str(meta.get("when", "")),
                        "notes": str(meta.get("notes", "")),
                    }
                    for key, meta in registry.items()
                ]
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "success": True,
                                    "data": {"methods": methods, "total": len(methods)},
                                },
                                indent=2,
                            ),
                        }
                    ],
                    "isError": False,
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "success": True,
                                "data": {"methods": list(registry), "total": len(registry)},
                            },
                            indent=2,
                        ),
                    }
                ],
                "isError": False,
            }
        except ImportError:
            pass
        try:
            mod = __import__("sports_data.books", fromlist=["books"])
        except ImportError:
            return _sports_module_unavailable(name)
        book_methods: tuple[str, ...] = getattr(mod, "METHODS", ())
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "data": {"methods": list(book_methods), "total": len(book_methods)},
                        },
                        indent=2,
                    ),
                }
            ],
            "isError": False,
        }
    for module_name, candidates in entry:
        try:
            mod = __import__(f"sports_data.{module_name}", fromlist=[module_name])
        except ImportError:
            continue
        fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
        if fn is None:
            continue
        kwargs = _sports_tool_kwargs(name, arguments)
        result = fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        # Handlers are usually async (get_all_books_odds, get_odds_multi) but
        # some are sync registry reads (books_coverage) — await only when the
        # callable actually returned a coroutine.
        import inspect

        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
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


# ── Climate / research domains (parallel build, guarded) ───────────────
# Candidate public function names for the climate_data / research_data
# modules. These packages land from parallel agents; every import below is
# guarded so the dispatcher degrades gracefully (a readable message) if a
# module has not landed yet. Each tool maps to one or more
# (module, candidate-callables) options tried in order, so the dispatcher
# resolves whichever module/function the landed code actually exposes.
_CLIMATE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_weather": (
        ("weather", ("get_forecast", "get_weather", "current_weather", "weather_now")),
    ),
    "pry_agri": (
        ("agri", ("get_crop_prices", "get_agri", "agri_report", "get_agriculture")),
        ("agriculture", ("get_crop_prices", "get_agri", "agri_report", "get_agriculture")),
    ),
}

_RESEARCH_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_papers": (
        ("academic", ("search_papers", "get_papers", "find_papers", "papers")),
        ("papers", ("search_papers", "get_papers", "find_papers", "papers")),
    ),
    "pry_domain": (
        ("domain", ("whois_lookup", "get_domain_report", "domain_report", "get_domain")),
        ("whois", ("whois_lookup", "get_domain_report", "domain_report", "get_domain")),
    ),
}


def _domain_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a climate/research tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the {package} module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for a climate/research tool from MCP arguments.

    Mirrors ``_sports_tool_kwargs``: kwargs the landed callable does not
    support are filtered out by the dispatcher (``_callable_accepts``) so the
    call never fails on an unknown keyword.
    """
    if name == "pry_weather":
        kwargs: dict[str, Any] = {"location": arguments.get("location", "")}
        if arguments.get("latitude") is not None and arguments.get("longitude") is not None:
            kwargs["location"] = f"{arguments['latitude']},{arguments['longitude']}"
        if arguments.get("forecast_days") is not None:
            kwargs["days"] = int(arguments["forecast_days"])
        return kwargs
    if name == "pry_agri":
        kwargs = {
            "commodity": arguments.get("crop", "") or arguments.get("commodity", ""),
            "state": arguments.get("region", "all") or arguments.get("state", "all"),
            "limit": int(arguments.get("limit", 20)),
        }
        return kwargs
    if name == "pry_papers":
        kwargs = {"query": arguments.get("query", ""), "limit": int(arguments.get("limit", 20))}
        if arguments.get("author"):
            kwargs["author"] = arguments["author"]
        if arguments.get("year_from") is not None:
            kwargs["year_from"] = int(arguments["year_from"])
        return kwargs
    if name == "pry_domain":
        kwargs = {"domain": arguments.get("domain", "")}
        if arguments.get("include_tech") is not None:
            kwargs["include_tech"] = bool(arguments["include_tech"])
        return kwargs
    return dict(arguments)


def _apply_offset(data: Any, arguments: dict[str, Any]) -> tuple[Any, int]:
    """Apply ``offset`` pagination to a list-shaped handler result.

    Returns ``(page, total)`` where ``total`` is the pre-slice length. When
    ``offset`` is absent/0 the data passes through unchanged. Non-list data
    (dicts, scalars) is returned untouched with total 0.
    """
    if not isinstance(data, list):
        return data, 0
    total = len(data)
    try:
        offset = int(arguments.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    if offset <= 0:
        return data, total
    return data[offset:], total


async def _call_domain_dispatcher(
    name: str,
    arguments: dict[str, Any],
    package: str,
    registry: dict[str, tuple[tuple[str, tuple[str, ...]], ...]],
    kwargs_builder: Any,
    required_args: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Run a climate/research tool via a candidate registry with guarded import.

    Tries each (module, candidates) option in order; the first landed module
    that exposes one of the candidate callables wins. Missing required
    arguments are reported as a tool error; a fully missing module degrades
    to a readable "not available" message.
    """
    entry = registry.get(name)
    if entry is None:
        return None
    required_args = required_args or {"pry_papers": "query", "pry_domain": "domain"}
    if name in required_args and not arguments.get(required_args[name]):
        return _missing_arg(name, required_args[name])
    for module_name, candidates in entry:
        try:
            mod = __import__(f"{package}.{module_name}", fromlist=[module_name])
        except ImportError:
            continue
        fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
        if fn is None:
            continue
        kwargs = kwargs_builder(name, arguments)
        # Offset pagination: over-fetch by ``offset`` so the slice below
        # still yields a full ``limit``-sized page past the skipped rows.
        try:
            _offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError):
            _offset = 0
        if _offset > 0:
            kwargs["limit"] = int(kwargs.get("limit") or 20) + _offset
        result = fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        # Handlers are usually async (events/freight/energy/...) but some
        # landed modules expose sync registry reads (app-store/news/
        # compliance/deals) — await only when the callable returned a
        # coroutine.
        import inspect

        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        data, total = _apply_offset(data, arguments)
        payload: dict[str, Any] = {"success": True, "data": data}
        if total:
            payload["total"] = total
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2),
                }
            ],
            "isError": False,
        }
    return _domain_module_unavailable(name, package)


async def call_climate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch climate MCP tools to their ``climate_data`` handlers (guarded).

    The ``climate_data`` subpackage (weather, agri) is built in parallel by
    other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-climate tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name, arguments, "climate_data", _CLIMATE_TOOL_FNS, _domain_tool_kwargs
    )


async def call_research_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch research MCP tools to their ``research_data`` handlers (guarded).

    The ``research_data`` subpackage (papers, domain) is built in parallel by
    other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-research tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name, arguments, "research_data", _RESEARCH_TOOL_FNS, _domain_tool_kwargs
    )


# ── Events / freight / energy / food / supply domains (parallel build) ──
# Candidate public function names for the five new data-domain packages
# (events_data, freight_data, energy_data, food_data, supply_data). These
# packages land from parallel agents; every import below is guarded so the
# dispatchers degrade gracefully (a readable message) if a module has not
# landed yet. Each tool maps to one or more (module, candidate-callables)
# options tried in order, mirroring the sports/climate pattern.
_EVENTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_events": (("tickets", ("search_events", "find_events", "get_events", "events")),),
    "pry_resale": (("tickets", ("get_resale_prices", "resale_prices", "get_resale")),),
}

_FREIGHT_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_freight": (("rates", ("get_container_rates", "get_fmc_contracts", "container_rates")),),
}

_ENERGY_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_energy_lmp": (
        (
            "lmp",
            (
                "get_lmp",
                "get_lmp_prices",
                "lmp_prices",
                "get_fuel_prices",
                "fuel_prices",
            ),
        ),
    ),
}

_FOOD_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_grocery": (("grocery", ("get_grocery_prices", "grocery_prices", "get_prices")),),
    "pry_restaurant": (("restaurants", ("get_restaurant_menu", "restaurant_menu", "get_menu")),),
}

_SUPPLY_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_imports": (("imports", ("get_import_records", "import_records", "get_imports")),),
    "pry_firmographics": (
        (
            "firmographics",
            (
                "get_company_firmographics",
                "company_firmographics",
                "get_firmographics",
            ),
        ),
    ),
}


def _broad_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an events/freight/energy/food/supply tool.

    Mirrors ``_domain_tool_kwargs`` / ``_sports_tool_kwargs``: kwargs the
    landed callable does not support are filtered out by the dispatcher
    (``_callable_accepts``) so the call never fails on an unknown keyword.
    """
    if name == "pry_events":
        return {
            "query": arguments.get("query", ""),
            "limit": int(arguments.get("limit", 20)),
        }
    if name == "pry_resale":
        return {"event_id": arguments.get("event_id", "")}
    if name == "pry_freight":
        kwargs: dict[str, Any] = {"route": arguments.get("route", "")}
        if arguments.get("origin"):
            kwargs["origin"] = arguments["origin"]
        if arguments.get("destination"):
            kwargs["destination"] = arguments["destination"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_energy_lmp":
        kwargs = {"region": arguments.get("region", "") or arguments.get("region_id", "")}
        if arguments.get("date"):
            kwargs["date"] = arguments["date"]
        return kwargs
    if name == "pry_grocery":
        kwargs = {"query": arguments.get("query", "") or arguments.get("item", "")}
        if arguments.get("zip"):
            kwargs["zip"] = arguments["zip"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_restaurant":
        kwargs = {"name": arguments.get("name", "")}
        if arguments.get("location"):
            kwargs["location"] = arguments["location"]
        return kwargs
    if name == "pry_imports":
        kwargs = {"company": arguments.get("company", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_firmographics":
        return {"company": arguments.get("company", "")}
    return dict(arguments)


async def call_events_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch events-data MCP tools to their ``events_data`` handlers (guarded).

    The ``events_data`` subpackage (``tickets``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-events tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "events_data",
        _EVENTS_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_events": "query", "pry_resale": "event_id"},
    )


async def call_freight_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch freight-data MCP tools to their ``freight_data`` handlers (guarded).

    The ``freight_data`` subpackage (``rates``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-freight tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "freight_data",
        _FREIGHT_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_freight": "route"},
    )


async def call_energy_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch energy-data MCP tools to their ``energy_data`` handlers (guarded).

    The ``energy_data`` subpackage (``lmp``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully (a
    readable message) if a module has not landed yet. Returns ``None`` for
    non-energy tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "energy_data",
        _ENERGY_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_energy_lmp": "region"},
    )


async def call_food_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch food-data MCP tools to their ``food_data`` handlers (guarded).

    The ``food_data`` subpackage (``grocery``, ``restaurants``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-food tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "food_data",
        _FOOD_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_grocery": "query", "pry_restaurant": "name"},
    )


async def call_supply_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch supply-data MCP tools to their ``supply_data`` handlers (guarded).

    The ``supply_data`` subpackage (``imports``, ``firmographics``) is built
    in parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-supply tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "supply_data",
        _SUPPLY_TOOL_FNS,
        _broad_domain_tool_kwargs,
        required_args={"pry_imports": "company", "pry_firmographics": "company"},
    )


# ── App store / news / compliance / deals domains (parallel build) ──────
# Candidate public function names for the four newest data-domain packages
# (app_store_data, news_data, compliance_data, deals_data). These packages
# land from parallel agents; every import below is guarded so the dispatchers
# degrade gracefully (a readable message) if a module has not landed yet.
# Each tool maps to one or more (module, candidate-callables) options tried
# in order, mirroring the events/freight/energy/food/supply pattern.
_APP_STORE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_app_search": (("apple", ("search_apps", "app_search", "search_products", "search")),),
    "pry_app_reviews": (("apple", ("get_reviews", "app_reviews", "get_app_reviews")),),
}

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

_COMPLIANCE_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_compliance": (
        (
            "enforcement",
            (
                "search_enforcement",
                "search_compliance",
                "compliance_search",
                "check_compliance",
                "get_compliance",
            ),
        ),
    ),
    "pry_company_watch": (
        ("enforcement", ("watch_company", "company_watch", "get_company_watch")),
    ),
}

_DEALS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_deals": (
        ("coupons", ("search_deals", "get_deals", "deals_search", "find_deals")),
        ("drops", ("search_deals", "get_deals", "deals_search")),
    ),
    "pry_drop_alert": (
        (
            "drops",
            ("check_drop_alerts", "list_alerts", "get_drop_alerts", "drop_alerts"),
        ),
    ),
}

# Candidate public function names for the bidding-data package
# (bidding_data.contracts, bidding_data.grants). The package lands from a
# parallel agent; every import below is guarded so the dispatchers degrade
# gracefully (a readable message) if a module has not landed yet. Mirrors the
# app-store / news / compliance / deals pattern.
_BIDDING_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_contracts": (
        ("contracts", ("search_contracts", "get_contracts", "contracts_search", "find_contracts")),
    ),
    "pry_grants": (("grants", ("search_grants", "get_grants", "grants_search", "find_grants")),),
}


def _new_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an app-store / news / compliance / deals tool.

    Mirrors ``_broad_domain_tool_kwargs`` / ``_domain_tool_kwargs``: kwargs
    the landed callable does not support are filtered out by the dispatcher
    (``_callable_accepts``) so the call never fails on an unknown keyword.
    """
    if name == "pry_app_search":
        kwargs: dict[str, Any] = {"query": arguments.get("query", "")}
        if arguments.get("country"):
            kwargs["country"] = arguments["country"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_app_reviews":
        kwargs = {"app_id": arguments.get("app_id", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_news":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("language"):
            kwargs["language"] = arguments["language"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_sentiment":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_compliance":
        kwargs = {}
        if arguments.get("query"):
            kwargs["query"] = arguments["query"]
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_company_watch":
        kwargs = {"company": arguments.get("company", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_deals":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_drop_alert":
        kwargs = {"product": arguments.get("product", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_contracts":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_grants":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    return dict(arguments)


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


async def call_compliance_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch compliance-data MCP tools to their ``compliance_data`` handlers (guarded).

    ``pry_compliance`` keeps a legacy URL-check mode: when called with only a
    ``url`` (no ``query``/``agency``) this dispatcher returns ``None`` so the
    original legal-risk REST proxy (``POST /v1/compliance/check``) keeps
    serving that mode while the ``compliance_data`` package lands. With
    ``query``/``agency`` it dispatches to the regulatory search. All imports
    are guarded so a missing module degrades to a readable message. Returns
    ``None`` for non-compliance tools so callers fall through.
    """
    if name == "pry_compliance" and not arguments.get("query") and not arguments.get("agency"):
        return None
    return await _call_domain_dispatcher(
        name,
        arguments,
        "compliance_data",
        _COMPLIANCE_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_company_watch": "company"},
    )


async def call_deals_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch deals MCP tools to their ``deals_data`` handlers (guarded).

    The ``deals_data`` subpackage (``deals``, ``drops``) is built in parallel
    by other agents; every import is guarded so this dispatcher degrades
    gracefully (a readable message) if a module has not landed yet. Returns
    ``None`` for non-deals tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "deals_data",
        _DEALS_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_deals": "query", "pry_drop_alert": "product"},
    )


async def call_bidding_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch bidding-data MCP tools to their ``bidding_data`` handlers (guarded).

    The ``bidding_data`` subpackage (``contracts``, ``grants``) is built in
    parallel by other agents; every import is guarded so this dispatcher
    degrades gracefully (a readable message) if a module has not landed yet.
    Returns ``None`` for non-bidding tools so callers fall through.
    """
    return await _call_domain_dispatcher(
        name,
        arguments,
        "bidding_data",
        _BIDDING_TOOL_FNS,
        _new_domain_tool_kwargs,
        required_args={"pry_contracts": "query", "pry_grants": "query"},
    )


# ── Apify actor parity layer ─────────────────────────────────────────────────
#
# Store parity: every Pry Apify Actor is reachable from MCP. Instead of one
# near-duplicate tool definitions (tool-list bloat breaks MCP clients), the
# surface is catalog-driven: ``pry_actor_catalog`` discovers, ``pry_actor_run``
# executes through the SAME PPEScraperRunner.process_url + PROCESSORS code
# path the deployed actors use on the platform.


def _actor_catalog_entries() -> list[dict[str, Any]]:
    """Catalog rows for every preset, sorted by name for determinism."""
    from actor_factory.metadata import PRESET_CATEGORY_MAP
    from actor_factory.presets import ALL_PRESETS

    entries: list[dict[str, Any]] = []
    for name in sorted(ALL_PRESETS):
        spec = ALL_PRESETS[name]
        entries.append(
            {
                "actor": spec.name.removeprefix("pry-"),
                "title": spec.title,
                "description": spec.description,
                "category": PRESET_CATEGORY_MAP.get(spec.name, "OTHER"),
                "icon": spec.icon,
                "icon_hd": spec.icon_hd,
                "processor": spec.processor,
                "uses_browser": spec.uses_browser,
                "min_memory_mbytes": spec.min_memory_mbytes,
                "pricing_events": [
                    {
                        "event": e.name,
                        "title": e.title,
                        "price_usd": e.price_usd,
                    }
                    for e in spec.pricing_events
                ],
            }
        )
    return entries


def _actor_tool_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Options dict passed through to the actor pipeline (everything except
    the runner's own control keys)."""
    return {k: v for k, v in arguments.items() if k not in ("actor", "urls", "max_items")}


async def call_actor_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the Apify-parity tools (catalog + run). Returns None for
    non-actor tools so callers fall through to other dispatchers."""
    if name == "pry_actor_catalog":
        domain = arguments.get("domain")
        entries = _actor_catalog_entries()
        if domain:
            needle = str(domain).lower()
            entries = [e for e in entries if needle in e["actor"] or needle in e["title"].lower()]
        # offset/limit pagination over the (109+) row catalog.
        try:
            offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        limit = arguments.get("limit")
        total = len(entries)
        if offset > 0:
            entries = entries[offset:]
        if isinstance(limit, int) and limit > 0:
            entries = entries[:limit]
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "total": total,
                            "count": len(entries),
                            "actors": entries,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    if name == "pry_actor_run":
        from actor_factory.presets import ALL_PRESETS
        from actor_factory.processors import PROCESSORS
        from actor_factory.runner import ActorRunConfig, PPEScraperRunner

        actor = arguments.get("actor")
        urls = arguments.get("urls") or []
        if not actor or not isinstance(actor, str):
            return _missing_arg(name, "actor")
        spec = ALL_PRESETS.get(f"pry-{actor}")
        if spec is None:
            known = ", ".join(sorted(a.removeprefix("pry-") for a in ALL_PRESETS))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": f"unknown actor '{actor}'. Known actors: {known}",
                                "code": "UNKNOWN_ACTOR",
                            }
                        ),
                    }
                ],
                "isError": True,
            }
        if not urls:
            return _missing_arg(name, "urls")

        max_items = arguments.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            max_items = 25
        options = _actor_tool_kwargs(arguments)
        options.setdefault("output_format", "markdown")

        config = ActorRunConfig(
            primary_event=spec.pricing_events[0].name if spec.pricing_events else "item",
            processor_name=spec.processor,
        )
        runner = PPEScraperRunner(config)
        processor = PROCESSORS.get(spec.processor) if spec.processor else None

        items: list[dict[str, Any]] = []
        state: dict[str, Any] = {}
        for url in list(urls)[:max_items]:
            try:
                item = await runner.process_url(url, options)
            except Exception as e:  # noqa: BLE001 - bad targets must not kill batches
                item = {
                    "url": url,
                    "status": "error",
                    "error": f"processing_failed: {str(e)[:120]}",
                }
            if processor is not None:
                item = processor(url, item, options, state)
            items.append(item)

        charged = spec.pricing_events[0].price_usd * len(items) if spec.pricing_events else 0.0
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "actor": spec.name.removeprefix("pry-"),
                            "items": items,
                            "item_count": len(items),
                            "format": options.get("output_format", "markdown"),
                            "equivalent_apify_charge_usd": round(charged, 6),
                            "note": (
                                "Ran locally via MCP - same pipeline as the Apify "
                                "actor; on-platform runs bill the equivalent PPE event."
                            ),
                        },
                        indent=2,
                        default=str,
                    ),
                }
            ]
        }

    return None


ACTOR_TOOL_NAMES: frozenset[str] = frozenset({"pry_actor_catalog", "pry_actor_run"})


def _sync_actor_catalog_description() -> None:
    """Keep the pry_actor_catalog description's actor count honest.

    ALL_PRESETS grows over time; a hardcoded count in the static tool list
    drifts (it said 94 when the table reached 109). Patch the description
    with the live len(ALL_PRESETS) at import; on any import failure fall
    back to the neutral wording (no count).
    """
    try:
        from actor_factory.presets import ALL_PRESETS

        count = len(ALL_PRESETS)
    except ImportError:  # pragma: no cover - presets not installed yet
        count = None
    for tool in PRY_TOOLS:
        if tool.get("name") == "pry_actor_catalog":
            if count is not None:
                tool["description"] = tool["description"].replace("(94)", f"({count})")
            else:
                tool["description"] = tool["description"].replace(" (94)", "")
            break


_sync_actor_catalog_description()
