"""Pry - MCP resource and prompt definitions.

PRY_RESOURCES and PRY_PROMPTS lists for the MCP server.

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

# ── Resource Definitions (per MCP spec) ──

PRY_RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "pry://catalog",
        "name": "Scraper Template Catalog",
        "description": "All 110+ available scraper templates organized by category. Use pry_search_templates tool for dynamic queries.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["user", "assistant"],
            "priority": 0.9,
        },
    },
    {
        "uri": "pry://stats",
        "name": "Pry Server Statistics",
        "description": (
            "Current Pry MCP server statistics: server name and version, protocol "
            "version, and live tool/resource/prompt counts. Use to confirm which "
            "server build and how many tools are registered."
        ),
        "mimeType": "application/json",
        "annotations": {
            "audience": ["assistant"],
            "priority": 0.5,
        },
    },
    {
        "uri": "pry://x402/pricing",
        "name": "x402 Pay-per-call Pricing",
        "description": "x402 pricing for all paid operations. Use to display cost to users before they make a paid call.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["user", "assistant"],
            "priority": 0.8,
        },
    },
    {
        "uri": "pry://referrals",
        "name": "Referral Catalog",
        "description": "Pry's referral program catalog. 60+ providers with affiliate links for revenue sharing.",
        "mimeType": "application/json",
        "annotations": {
            "audience": ["assistant"],
            "priority": 0.3,
        },
    },
    {
        "uri": "pry://coverage",
        "name": "Site Catalog Coverage",
        "description": (
            "Summary of Pry's site capability catalog: how many target sites are "
            "covered, grouped by data domain, scrape method, and anti-bot "
            "posture. Use to see which sites Pry can already handle before "
            "scraping."
        ),
        "mimeType": "application/json",
        "annotations": {
            "audience": ["assistant"],
            "priority": 0.4,
        },
    },
    {
        "uri": "pry://domains",
        "name": "Data Domains",
        "description": (
            "The 17+ data domains served by Pry (scraping primitives plus the "
            "intelligence packages: crypto, marketplace, legal, real estate, "
            "jobs, travel, attention, local, healthcare, commerce, gov, IP, "
            "climate, research, events, freight, energy, food, supply). Use to "
            "discover which domains exist and the tools that cover each."
        ),
        "mimeType": "application/json",
        "annotations": {
            "audience": ["user", "assistant"],
            "priority": 0.6,
        },
    },
]

# ── Data-domain catalog (for pry://domains) ──
# The 17+ data domains served by Pry. "Core" entries are the scraper
# primitives; "intelligence" entries are the data packages monetized via
# x402. Tool names reference PRY_TOOLS.
DATA_DOMAINS: list[dict[str, Any]] = [
    {
        "id": "scrape",
        "name": "Web scraping",
        "kind": "core",
        "description": "Scrape any URL to markdown with a 9-tier anti-bot fallback chain.",
        "tools": ["pry_scrape", "pry_crawl", "pry_extract"],
    },
    {
        "id": "templates",
        "name": "Scraper templates",
        "kind": "core",
        "description": "110+ pre-built scrapers for specific sites and page types.",
        "tools": ["pry_template", "pry_search_templates"],
    },
    {
        "id": "monitoring",
        "name": "Page monitoring",
        "kind": "core",
        "description": "Watch pages for changes and alert via webhook/Slack/Discord.",
        "tools": ["pry_monitor"],
    },
    {
        "id": "compliance",
        "name": "Scraping compliance",
        "kind": "core",
        "description": "Score legal risk of a scrape (robots.txt, ToS, GDPR/CCPA).",
        "tools": ["pry_compliance"],
    },
    {
        "id": "enrichment",
        "name": "Lead enrichment",
        "kind": "core",
        "description": "Enrich a URL with company, tech-stack, and social intel.",
        "tools": ["pry_enrich"],
    },
    {
        "id": "documents",
        "name": "Document parsing",
        "kind": "core",
        "description": "Parse PDF/DOCX/images into text and tables.",
        "tools": ["pry_parse_document"],
    },
    {
        "id": "crypto",
        "name": "Crypto market",
        "kind": "intelligence",
        "description": "Token launches, CEX listings, and token security checks.",
        "tools": ["pry_token_launches", "pry_cex_listings", "pry_token_security"],
    },
    {
        "id": "marketplace",
        "name": "Marketplace",
        "kind": "intelligence",
        "description": "Product lookups and trending items (Amazon, Walmart, TikTok Shop).",
        "tools": [
            "pry_amazon_product",
            "pry_amazon_search",
            "pry_walmart_product",
            "pry_tiktok_trending",
        ],
    },
    {
        "id": "sports",
        "name": "Sports betting",
        "kind": "intelligence",
        "description": "Odds, arbitrage, +EV, props, injuries, live odds, scores, alerts.",
        "tools": [
            "pry_odds",
            "pry_arbitrage",
            "pry_plus_ev",
            "pry_props",
            "pry_injuries",
            "pry_live_odds",
            "pry_scores",
            "pry_historical_odds",
            "pry_betting_percentages",
            "pry_sharp_consensus",
            "pry_alerts",
        ],
    },
    {
        "id": "legal",
        "name": "Legal & public records",
        "kind": "intelligence",
        "description": "Court dockets, SEC filings, and OFAC sanctions screening.",
        "tools": ["pry_legal_dockets", "pry_legal_sec", "pry_legal_sanctions"],
    },
    {
        "id": "realestate",
        "name": "Real estate",
        "kind": "intelligence",
        "description": "Property listings by location and status.",
        "tools": ["pry_realestate_search"],
    },
    {
        "id": "jobs",
        "name": "Jobs & careers",
        "kind": "intelligence",
        "description": "ATS job postings and salary bands.",
        "tools": ["pry_jobs_list", "pry_jobs_salary"],
    },
    {
        "id": "travel",
        "name": "Travel",
        "kind": "intelligence",
        "description": "Flight price grids and hotel rates.",
        "tools": ["pry_flights_grid", "pry_hotel_rates"],
    },
    {
        "id": "attention",
        "name": "Attention & SEO",
        "kind": "intelligence",
        "description": "Google SERP scrapes and trend timelines.",
        "tools": ["pry_serp", "pry_trends"],
    },
    {
        "id": "local",
        "name": "Local business",
        "kind": "intelligence",
        "description": "Google Maps business search and reviews.",
        "tools": ["pry_places_search", "pry_reviews"],
    },
    {
        "id": "gov",
        "name": "Government data",
        "kind": "intelligence",
        "description": "Federal procurement opportunities and product recalls.",
        "tools": ["pry_procurement", "pry_recalls"],
    },
    {
        "id": "ip",
        "name": "IP data",
        "kind": "intelligence",
        "description": "Patent and trademark searches via USPTO.",
        "tools": ["pry_patents", "pry_trademarks"],
    },
    {
        "id": "climate",
        "name": "Climate / weather & agriculture",
        "kind": "intelligence",
        "description": "NOAA weather forecasts and USDA crop data.",
        "tools": ["pry_weather", "pry_agri"],
    },
    {
        "id": "research",
        "name": "Research & academic",
        "kind": "intelligence",
        "description": "Academic paper search and domain intelligence reports.",
        "tools": ["pry_papers", "pry_domain"],
    },
    {
        "id": "events",
        "name": "Events & ticketing",
        "kind": "intelligence",
        "description": "Event search and resale ticket pricing.",
        "tools": ["pry_events", "pry_resale"],
    },
    {
        "id": "freight",
        "name": "Freight",
        "kind": "intelligence",
        "description": "Ocean container rates and FMC contracts.",
        "tools": ["pry_freight"],
    },
    {
        "id": "energy",
        "name": "Energy",
        "kind": "intelligence",
        "description": "Electricity locational marginal prices (LMP) and fuel prices.",
        "tools": ["pry_energy_lmp"],
    },
    {
        "id": "food",
        "name": "Food & grocery",
        "kind": "intelligence",
        "description": "Grocery prices by item/ZIP and restaurant menu pricing.",
        "tools": ["pry_grocery", "pry_restaurant"],
    },
    {
        "id": "supply",
        "name": "Supply chain",
        "kind": "intelligence",
        "description": "U.S. customs import records and company firmographics.",
        "tools": ["pry_imports", "pry_firmographics"],
    },
]

# ── Prompt Definitions (per MCP spec) ──

PRY_PROMPTS: list[dict[str, Any]] = [
    {
        "name": "research_company",
        "title": "Research a Company",
        "description": "Scrape and analyze a company website for competitive intelligence. Use the pry_scrape and pry_enrich tools to gather data, then summarize findings.",
        "arguments": [
            {
                "name": "company_name",
                "description": "Company name (e.g., 'Anthropic')",
                "required": True,
            },
            {
                "name": "website",
                "description": "Company website URL (e.g., 'https://anthropic.com')",
                "required": True,
            },
        ],
    },
    {
        "name": "compare_products",
        "title": "Compare Products",
        "description": "Scrape product pages from multiple e-commerce sites and create a side-by-side comparison. Use pry_template tool with amazon-product, walmart-product, etc.",
        "arguments": [
            {
                "name": "product_query",
                "description": "What to search for (e.g., 'wireless headphones')",
                "required": True,
            },
            {
                "name": "sites",
                "description": "Sites to compare (e.g., ['amazon', 'walmart', 'target'])",
                "required": True,
            },
        ],
    },
    {
        "name": "extract_contacts",
        "title": "Extract Contacts from a Website",
        "description": "Crawl a website and extract all email addresses, phone numbers, and social media handles using CSS selectors and regex patterns.",
        "arguments": [
            {"name": "url", "description": "Starting URL", "required": True},
            {
                "name": "max_pages",
                "description": "Maximum pages to crawl (default: 20)",
                "required": False,
            },
        ],
    },
    {
        "name": "monitor_competitor",
        "title": "Monitor a Competitor",
        "description": "Set up continuous monitoring for a competitor's pricing, product listings, or content. Get notified via webhook on changes.",
        "arguments": [
            {"name": "url", "description": "Competitor URL to monitor", "required": True},
            {
                "name": "what_to_track",
                "description": "What to track (e.g., 'product prices', 'blog posts', 'job listings')",
                "required": True,
            },
            {"name": "webhook_url", "description": "Where to send notifications", "required": True},
        ],
    },
    {
        "name": "analyze_article",
        "title": "Analyze an Article",
        "description": "Scrape an article, summarize key points, and provide structured analysis (sentiment, entities, key claims).",
        "arguments": [
            {"name": "url", "description": "Article URL", "required": True},
            {
                "name": "focus",
                "description": "What to focus on (e.g., 'financial implications', 'competitive threats')",
                "required": False,
            },
        ],
    },
    {
        "name": "extract_table",
        "title": "Extract a Data Table",
        "description": "Find and extract a specific data table from a webpage. Returns structured CSV/JSON rows.",
        "arguments": [
            {"name": "url", "description": "Page URL", "required": True},
            {
                "name": "table_description",
                "description": "Description of the table you want (e.g., 'product pricing table', 'league standings')",
                "required": True,
            },
        ],
    },
    {
        "name": "scrape_with_schema",
        "title": "Scrape with Custom Schema",
        "description": "Scrape any URL with a custom JSON schema. Use pry_extract or pry_scrape with a schema definition.",
        "arguments": [
            {"name": "url", "description": "URL to scrape", "required": True},
            {
                "name": "fields",
                "description": "Comma-separated list of fields to extract (e.g., 'title,price,description,image')",
                "required": True,
            },
        ],
    },
]
