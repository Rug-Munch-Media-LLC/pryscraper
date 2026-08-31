# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""x402 well-known endpoints for marketplace discovery.

Implements the x402 discovery protocol so AI agents and marketplaces
can find and interact with Pry's paid API surface.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Discovery"])


@router.get("/.well-known/x402.json")
async def x402_manifest() -> dict[str, Any]:
    """Return the x402 discovery manifest.

    This manifest tells AI agents and marketplaces:
    - Which endpoints are paid
    - What payment methods are accepted (USDC, USDT, SOL, TRX)
    - Pricing for each operation
    - Supported networks (EVM, Solana, TRON)

    See: https://docs.x402.org/discovery
    """
    return {
        "name": "Pry Scraping API",
        "description": "Pay-per-request web scraping API with x402 payments",
        "version": "3.0.0",
        "payment": {
            "x402": {
                "enabled": True,
                "facilitator": "self-hosted",
                "supported_networks": [
                    "eip155:8453",  # Base
                    "eip155:1",  # Ethereum
                    "eip155:42161",  # Arbitrum
                    "eip155:10",  # Optimism
                    "eip155:137",  # Polygon
                    "solana:mainnet",  # Solana
                    "tron:mainnet",  # TRON
                ],
                "supported_assets": ["USDC", "USDT", "ETH", "SOL", "TRX", "ARB", "POL", "WETH"],
            }
        },
        "endpoints": {
            "/v1/scrape": {
                "description": "Scrape any URL with 15-tier fallback",
                "methods": ["POST"],
                "pricing": {
                    "base": "$0.001",
                    "per_page": "$0.0005",
                    "tiers": {
                        "free": {"requests_per_minute": 10, "pages": 1},
                        "pro": {"requests_per_minute": 60, "pages": 5, "price": "$9/mo"},
                        "enterprise": {"requests_per_minute": 300, "pages": 20, "price": "$49/mo"},
                    },
                },
            },
            "/v1/crawl": {
                "description": "Crawl entire websites",
                "methods": ["POST"],
                "pricing": {"base": "$0.005", "per_page": "$0.001"},
            },
            "/v1/extract": {
                "description": "AI-powered structured extraction",
                "methods": ["POST"],
                "pricing": {"base": "$0.003", "per_field": "$0.0005"},
            },
            "/v1/search": {
                "description": "Search engine scraping",
                "methods": ["POST"],
                "pricing": {"base": "$0.002", "per_result": "$0.0001"},
            },
            "/v1/signup": {
                "description": "Automated account registration",
                "methods": ["POST"],
                "pricing": {"base": "$0.01", "per_site": "$0.005"},
            },
            "/v1/auth/captcha": {
                "description": "CAPTCHA solving service",
                "methods": ["POST"],
                "pricing": {"per_captcha": "$0.005"},
            },
        },
        "mcp": {
            "enabled": True,
            "url": "/mcp",
            "transport": ["sse", "stdio"],
        },
        "contact": {
            "website": "https://[INTERNAL]",
            "docs": "https://docs.pryscraper.com",
            "support": "support@rugmunch.io",
        },
    }


@router.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    """Return the agent card for AI agent discovery."""
    return {
        "name": "Pry Scraping Agent",
        "description": "Web scraping agent with x402 payment integration",
        "version": "3.0.0",
        "capabilities": [
            "web_scraping",
            "website_crawling",
            "data_extraction",
            "search_scraping",
            "account_signup",
            "captcha_solving",
        ],
        "payment": {
            "x402": True,
            "crypto": ["BTC", "ETH", "SOL", "USDC", "USDT", "TRX"],
        },
        "mcp": {
            "url": "/mcp",
            "transport": ["sse", "stdio"],
        },
    }


@router.get("/.well-known/x402-bazaar.json")
async def x402_bazaar() -> dict[str, Any]:
    """Return the x402 Bazaar listing for marketplace indexing."""
    from pry.api.registry_metadata import get_registry_manifest

    manifest = get_registry_manifest()
    return {
        "seller": {
            "id": manifest["name"],
            "name": manifest["displayName"],
            "description": manifest["description"],
            "website": manifest["website"],
        },
        "services": [
            {
                "id": t["name"].replace("pry_", ""),
                "name": t["name"].replace("pry_", "").replace("_", " ").title(),
                "description": t["description"][:200],
                "category": t["category"],
            }
            for t in manifest["tools"]["items"][:10]
        ],
        "payment": manifest["payment"],
    }


@router.get("/llms.txt")
async def llms_txt_endpoint() -> Response:
    """Return the llms.txt file for AI agent discovery (llms.txt standard)."""
    from fastapi.responses import PlainTextResponse

    from pry.api.registry_metadata import generate_llms_txt

    return PlainTextResponse(content=generate_llms_txt(), media_type="text/plain")
