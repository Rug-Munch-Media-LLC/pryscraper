# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP registry listing for Pry.

Registers Pry with MCP marketplaces so AI agents can discover and use
our paid scraping tools.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# MCP Registry endpoints
MCP_REGISTRIES = {
    "glama": {"url": "https://glama.ai/mcp", "submit": "/submit"},
    "smithery": {"url": "https://smithery.ai", "submit": "/submit"},
    "mcp_market": {"url": "https://mcp.market", "submit": "/submit"},
    "toolhouse": {"url": "https://www.toolhouse.ai", "submit": "/submit"},
    "mcp_get": {"url": "https://mcp.get", "submit": "/submit"},
}

# x402 marketplace registries
X402_REGISTRIES = {
    "x402_bazaar": {"url": "https://x402.org/bazaar", "submit": "/submit"},
    "x402scan": {"url": "https://x402scan.com", "submit": "/submit"},
    "cdp_bazaar": {"url": "https://cdp.coinbase.com/x402/bazaar", "submit": "/submit"},
}


def get_mcp_listing() -> dict[str, Any]:
    """Return the MCP registry listing for Pry."""
    return {
        "name": "pry-scraper",
        "displayName": "Pry Scraping API",
        "description": "Professional web scraping with x402 crypto payments. 15-tier anti-detection fallback, AI extraction, auto-signup, CAPTCHA solving.",
        "version": "3.0.0",
        "author": {"name": "Rug Munch Media LLC", "email": "admin@rugmunch.io"},
        "license": "MIT",
        "icon": "https://pryscraper.com/img/pry.png",
        "banner": "https://pryscraper.com/og.png",
        "website": "https://pryscraper.com",
        "docs": "https://docs.pryscraper.com",
        "mcp": {
            "url": "https://api.pryscraper.com/mcp/",
            "transport": ["sse", "stdio"],
        },
        "tools": [
            {"name": "scrape", "description": "Scrape any URL with 15-tier fallback"},
            {"name": "crawl", "description": "Crawl entire websites"},
            {"name": "extract", "description": "AI-powered structured extraction"},
            {"name": "search", "description": "Search engine scraping"},
            {"name": "signup", "description": "Automated account registration"},
            {"name": "captcha", "description": "CAPTCHA solving"},
            {"name": "screenshot", "description": "Full-page screenshots"},
            {"name": "monitor", "description": "Website change monitoring"},
            {"name": "enrich", "description": "Data enrichment"},
            {"name": "compliance", "description": "Compliance checking"},
        ],
        "payment": {
            "x402": True,
            "crypto": ["BTC", "ETH", "SOL", "USDC", "USDT", "TRX"],
            "fiat": ["USD"],
        },
        "pricing": {
            "model": "pay_per_request",
            "tiers": [
                {"name": "free", "price": 0, "requests_per_minute": 10},
                {"name": "pro", "price": 9, "requests_per_minute": 60, "period": "month"},
                {"name": "enterprise", "price": 49, "requests_per_minute": 300, "period": "month"},
            ],
        },
        "tags": ["scraping", "web", "data", "x402", "crypto", "ai-agents", "mcp"],
        "categories": ["developer-tools", "data", "ai-agents"],
        "featured": True,
    }


def get_x402_listing() -> dict[str, Any]:
    """Return the x402 marketplace listing for Pry."""
    return {
        "seller": {
            "id": "pry-scraper",
            "name": "Pry Scraping API",
            "description": "Professional web scraping with crypto payments",
            "website": "https://pryscraper.com",
            "icon": "https://pryscraper.com/img/pry.png",
            "banner": "https://pryscraper.com/og.svg",
        },
        "services": [
            {
                "id": "scrape",
                "name": "Web Scraping",
                "description": "Scrape any URL with 15-tier anti-detection fallback",
                "price": {"amount": "0.001", "currency": "USD"},
                "network": "eip155:8453",
                "asset": "USDC",
                "endpoint": "https://api.pryscraper.com/v1/scrape",
            },
            {
                "id": "crawl",
                "name": "Website Crawling",
                "description": "Crawl entire websites with BFS discovery",
                "price": {"amount": "0.005", "currency": "USD"},
                "network": "eip155:8453",
                "asset": "USDC",
                "endpoint": "https://api.pryscraper.com/v1/crawl",
            },
            {
                "id": "extract",
                "name": "AI Extraction",
                "description": "LLM-powered structured data extraction",
                "price": {"amount": "0.003", "currency": "USD"},
                "network": "eip155:8453",
                "asset": "USDC",
                "endpoint": "https://api.pryscraper.com/v1/extract",
            },
            {
                "id": "signup",
                "name": "Account Signup",
                "description": "Automated account registration on any site",
                "price": {"amount": "0.01", "currency": "USD"},
                "network": "eip155:8453",
                "asset": "USDC",
                "endpoint": "https://api.pryscraper.com/v1/signup",
            },
            {
                "id": "captcha",
                "name": "CAPTCHA Solving",
                "description": "Solve reCAPTCHA, hCaptcha, Turnstile",
                "price": {"amount": "0.005", "currency": "USD"},
                "network": "eip155:8453",
                "asset": "USDC",
                "endpoint": "https://api.pryscraper.com/v1/auth/captcha",
            },
        ],
        "payment": {
            "x402": True,
            "crypto": True,
            "providers": ["coinbase_commerce", "nowpayments", "btcpay"],
        },
        "contact": {
            "email": "admin@rugmunch.io",
            "website": "https://pryscraper.com",
        },
    }


def generate_registry_submissions() -> dict[str, Any]:
    """Generate submission payloads for all registries."""
    return {
        "mcp": get_mcp_listing(),
        "x402": get_x402_listing(),
    }
