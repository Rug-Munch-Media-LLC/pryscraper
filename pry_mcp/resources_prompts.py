"""Pry - MCP prompt definitions.

PRY_PROMPTS list for the MCP server.

Split from resources.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

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
