"""Static FastAPI app metadata: description, contact, license, tags, servers.

Pure declaration block extracted from ``app_factory`` (structure ratchet,
2026-09-26) so the factory reads as wiring rather than a literal wall. Values
are byte-for-byte what the app shipped before the split — the generated
OpenAPI spec must not change.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

APP_DESCRIPTION = (
    "PryScraper is a self-hosted web scraping + browser automation platform. "
    "Scrape, crawl, parse and extract structured data from any website with a "
    "10-tier anti-bot fallback system, then monetize paid operations with x402 "
    "micropayments (pay-per-scrape over HTTP 402). Free endpoints are always "
    "public; paid endpoints are gated behind on-chain x402 payments."
)

CONTACT: dict[str, str] = {
    "name": "Rug Munch Media LLC",
    "url": "https://pryscraper.com",
    "email": "admin@rugmunch.io",
}

LICENSE_INFO: dict[str, str] = {
    "name": "MIT",
    "url": "https://opensource.org/licenses/MIT",
}

TERMS_OF_SERVICE = "https://pryscraper.com/terms"

SERVERS: list[dict[str, str]] = [
    {"url": "http://localhost:8002", "description": "Local development server"},
    {"url": "https://api.pryscraper.com", "description": "Production API"},
]

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "Scraping",
        "description": "Core scraping, crawling and browser-automation endpoints. "
        "Scrape any URL with the 10-tier anti-bot fallback chain, capture network "
        "patterns, and run adaptive relevance-based crawls.",
    },
    {
        "name": "Extraction",
        "description": "Structured data extraction: HTML tables, links, SEO analysis, "
        "Schema.org/JSON-LD, emails, CSS-selector extraction and LLM-powered extraction "
        "with intelligent chunking.",
    },
    {
        "name": "Commerce",
        "description": "Commerce, marketplace, costing, billing and subscription "
        "endpoints for the hosted Pry platform.",
    },
    {
        "name": "Auth",
        "description": "Authentication and API-key management. Protected endpoints "
        "require an `Authorization: Bearer <key>` header (or an rmi JWT).",
    },
    {
        "name": "Health",
        "description": "Liveness and readiness probes for the Pry service.",
    },
    {
        "name": "MCP",
        "description": "Model Context Protocol server (mounted at `/mcp`) exposing "
        "Pry's scraping, crawling, extraction and domain tools to AI agents over "
        "streaming SSE.",
    },
    {
        "name": "x402",
        "description": "x402 micropayment endpoints: pricing, payment requests, "
        "on-chain verification and settlement for pay-per-scrape operations.",
    },
    {
        "name": "Monitoring",
        "description": "Observability, alerting and integration-monitoring endpoints.",
    },
]
