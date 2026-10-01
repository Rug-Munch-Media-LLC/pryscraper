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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Discovery"])


@router.get("/.well-known/x402.json")
async def x402_manifest() -> dict[str, Any]:
    """Return the x402 discovery manifest.

    This manifest tells AI agents and marketplaces:
    - Which endpoints are paid
    - What payment methods are accepted (USDC, USDT, SOL)
    - Pricing for each operation
    - Supported networks (EVM, Solana)

    TRON is intentionally NOT advertised: scheme.py gates tron:mainnet
    (scaffolded — no TRC-20 settlement verifier is wired), so the manifest
    must not claim it either.

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
                # Mirrors scheme.py's LIVE acceptance surface. tron:mainnet is
                # excluded — VERIFICATION_STATUS marks it scaffolded and the
                # verify path rejects it; advertising it here would invite
                # payments we cannot verify/settle.
                "supported_networks": [
                    "eip155:8453",  # Base
                    "eip155:1",  # Ethereum
                    "eip155:42161",  # Arbitrum
                    "eip155:10",  # Optimism
                    "eip155:137",  # Polygon
                    "solana:mainnet",  # Solana
                ],
                "supported_assets": ["USDC", "USDT", "ETH", "SOL", "ARB", "POL", "WETH"],
                "pricing_endpoint": "/v1/x402/pricing",
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
            # NOTE: no /v1/search entry. Web search is exposed over MCP only
            # (pry_search / pry_search_web / pry_mega_search); there is no
            # REST route for it, so this manifest must not advertise a price
            # for it. scripts/check-doc-claims.py enforces this.
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
            "support": "support@pryscraper.com",
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
        "repository": {
            "source": "codeberg",
            "url": "https://codeberg.org/cryptorugmunch/pryscraper",
        },
        "contact": {
            "website": "https://pryscraper.com",
            "docs": "https://docs.pryscraper.com",
            "support": "support@pryscraper.com",
        },
        "mcp": {
            "url": "/mcp",
            "transport": ["sse", "stdio"],
        },
    }


def _load_server_json() -> str | None:
    """Read the canonical ``server.json`` manifest once at import time.

    Import-time (sync) read keeps blocking pathlib calls out of the async
    route (ruff ASYNC240) and caches the manifest for the process lifetime —
    deployments ship ``server.json`` with the image, so it does not change
    at runtime.
    """
    candidates = [
        Path(__file__).resolve().parents[5] / "server.json",
        Path.cwd() / "server.json",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


_SERVER_JSON_CACHE: str | None = _load_server_json()


@router.get("/.well-known/server.json")
async def mcp_server_manifest() -> Response:
    """Return the MCP registry server.json (server discovery manifest).

    Serves the canonical registry manifest shipped at the repository root
    (``server.json``): 76 tools, 6 resources, 7 prompts, version 3.0.0,
    Codeberg repository URL. Falls back to a minimal generated manifest when
    the file is not present in the deployment layout.
    """
    if _SERVER_JSON_CACHE is not None:
        return Response(content=_SERVER_JSON_CACHE, media_type="application/json")
    from pry.api.registry_metadata import get_registry_manifest

    manifest = get_registry_manifest()
    return JSONResponse(
        {
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.rugmunch/pry",
            "title": manifest.get("displayName", "Pry"),
            "description": manifest.get("description", ""),
            "version": manifest.get("version", "3.0.0"),
            "websiteUrl": manifest.get("website", "https://pryscraper.com"),
            "repository": {
                "source": "codeberg",
                "url": "https://codeberg.org/cryptorugmunch/pryscraper",
            },
            "remotes": [
                {
                    "type": "streamable-http",
                    "url": "https://api.pryscraper.com/mcp/",
                }
            ],
        }
    )


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
