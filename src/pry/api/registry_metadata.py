# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Dynamic MCP tool metadata for registry discovery.

Builds rich, bot-readable tool manifests with SEO-optimized descriptions,
registry metadata, and structured capability tags for each MCP registry
(Glama, Smithery, MCP Registry, Pulsemcp, llms.txt).

Top-tier MCP stores rank servers by:
  1. Description quality (bot-readable, use-case-driven, not feature lists)
  2. Tool count and diversity (73 tools across 12+ categories)
  3. Input/output schema completeness (every tool has both)
  4. Annotations (readOnlyHint, destructiveHint, idempotentHint)
  5. Structured metadata (categories, tags, use_cases, keywords)
  6. README quality (clear quickstart, badges, comparison tables)
  7. Well-known discovery endpoints (/.well-known/x402.json, agent.json)

This module implements all of the above.
"""

from __future__ import annotations

from typing import Any

from pry_mcp.tools import PRY_TOOLS


def _enrich_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Add registry metadata to a tool definition."""
    name = tool["name"]
    description = tool.get("description", "")

    # Derive category from name prefix
    category = _categorize(name)
    keywords = _keywords(name, description)
    use_cases = _use_cases(name, description)

    enriched = {
        **tool,
        "category": category,
        "keywords": keywords,
        "use_cases": use_cases,
        # Glama-specific: longer description for SEO
        "longDescription": _long_description(name, description),
        # Smithery-specific: tool grouping
        "group": category,
        # Pulsemcp-specific: capability tags
        "capabilities": _capabilities(name),
    }
    return enriched


def _categorize(name: str) -> str:
    """Categorize a tool by its name."""
    categories = {
        "scrape": "web_scraping",
        "crawl": "web_scraping",
        "extract": "data_extraction",
        "template": "web_scraping",
        "search_templates": "web_scraping",
        "monitor": "monitoring",
        "screenshot": "web_scraping",
        "parse_document": "document_processing",
        "compliance": "compliance",
        "enrich": "data_enrichment",
        "domain": "data_enrichment",
        "serp": "search",
        "trends": "search",
        "news": "news_intelligence",
        "weather": "data",
        "jobs": "jobs_careers",
        "realestate": "real_estate",
        "flights": "travel",
        "hotel_rates": "travel",
        "freight": "logistics",
        "energy": "energy",
        "grocery": "retail",
        "restaurant": "retail",
        "deals": "retail",
        "resale": "retail",
        "imports": "trade",
        "procurement": "government",
        "contracts": "government",
        "grants": "government",
        "legal": "legal",
        "patents": "legal",
        "trademarks": "legal",
        "sentiment": "social",
        "reviews": "social",
        "events": "events",
        "papers": "research",
        "odds": "sports_betting",
        "arbitrage": "sports_betting",
        "plus_ev": "sports_betting",
        "props": "sports_betting",
        "injuries": "sports_betting",
        "live_odds": "sports_betting",
        "scores": "sports_betting",
        "betting": "sports_betting",
        "historical": "sports_betting",
        "sharp": "sports_betting",
        "books": "sports_betting",
        "book_coverage": "sports_betting",
        "scrape_methods": "web_scraping",
        "all_sources": "sports_betting",
        "token": "crypto",
        "cex": "crypto",
        "firmographics": "business",
        "company": "business",
        "app": "app_store",
        "recommendations": "recommendations",
        "alerts": "alerts",
        "drop": "alerts",
        "referrals": "affiliate",
        "x402": "payments",
        "actor": "actors",
        "agri": "agriculture",
        "places": "local",
        "recall": "safety",
        "app_reviews": "app_store",
    }
    for prefix, cat in categories.items():
        if prefix in name:
            return cat
    return "utility"


def _keywords(name: str, description: str) -> list[str]:
    """Extract search keywords from tool name and description."""
    words = set()
    # Split name into parts
    parts = name.replace("pry_", "").replace("_", " ").split()
    words.update(parts)
    # Extract key terms from description
    key_terms = [
        "scrape",
        "crawl",
        "extract",
        "monitor",
        "search",
        "api",
        "cloudflare",
        "bypass",
        "markdown",
        "json",
        "data",
        "web",
        "automation",
        "browser",
        "screenshot",
        "template",
        "ai",
        "x402",
        "crypto",
        "payment",
        "mcp",
    ]
    desc_lower = description.lower()
    for term in key_terms:
        if term in desc_lower:
            words.add(term)
    return sorted(words)


def _use_cases(name: str, description: str) -> list[str]:
    """Extract use cases from description."""
    use_cases = []
    # Look for "Use when" or "Use to" patterns
    if "use when" in description.lower():
        idx = description.lower().index("use when")
        snippet = description[idx : idx + 200]
        use_cases.append(snippet.split(".")[0])
    if "use to" in description.lower():
        idx = description.lower().index("use to")
        snippet = description[idx : idx + 200]
        use_cases.append(snippet.split(".")[0])
    return use_cases[:3]


def _long_description(name: str, short_desc: str) -> str:
    """Build a longer, SEO-optimized description for Glama."""
    return (
        f"{short_desc} "
        f"Part of the Pry scraping platform — 73 tools, 15-tier anti-detection, "
        f"x402 crypto payments, self-hosted or cloud."
    )


def _capabilities(name: str) -> list[str]:
    """Map tool name to capability tags for Pulsemcp."""
    caps = []
    if "scrape" in name or "crawl" in name or "extract" in name:
        caps.append("web_scraping")
    if "monitor" in name:
        caps.append("monitoring")
    if "search" in name or "serp" in name or "trends" in name:
        caps.append("search")
    if "x402" in name or "payment" in name:
        caps.append("payments")
    if "actor" in name:
        caps.append("actors")
    if "template" in name:
        caps.append("templates")
    return caps or ["utility"]


def get_enriched_tools() -> list[dict[str, Any]]:
    """Return all tools enriched with registry metadata."""
    return [_enrich_tool(t) for t in PRY_TOOLS]


def get_tools_by_category() -> dict[str, list[dict[str, Any]]]:
    """Group tools by category for registry browsing."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for tool in get_enriched_tools():
        cat = tool["category"]
        by_cat.setdefault(cat, []).append(tool)
    return dict(sorted(by_cat.items()))


def get_registry_manifest() -> dict[str, Any]:
    """Build the full registry manifest for all MCP registries."""
    tools = get_enriched_tools()
    categories = get_tools_by_category()

    return {
        "name": "pry-scraper",
        "displayName": "Pry Scraping API",
        "description": (
            "Professional web scraping with x402 crypto payments. "
            "15-tier anti-detection fallback, AI extraction, auto-signup, CAPTCHA solving. "
            "73 MCP tools across web scraping, data extraction, monitoring, sports betting, "
            "legal intelligence, real estate, jobs, and more."
        ),
        "longDescription": (
            "Pry is a self-hosted web scraping and browser automation platform with "
            "native x402 micropayments. It routes each request through an adaptive "
            "15-tier fallback chain — direct HTTP, TLS fingerprint impersonation, "
            "cloudscraper, FlareSolverr, undetected-chromedriver, Camoufox, Playwright "
            "stealth, Googlebot UA, Tor, premium proxies, Archive.org, Google Cache, "
            "AI visual scraping, mobile app API, and GraphQL discovery — escalating only "
            "as far as the target requires, then remembering what worked per domain."
        ),
        "version": "3.0.0",
        "author": {
            "name": "Rug Munch Media LLC",
            "email": "admin@rugmunch.io",
        },
        "license": "MIT",
        "website": "https://[INTERNAL]",
        "docs": "https://docs.[INTERNAL]",
        "source": "https://git.rugmunch.io/RugMunchMedia/pryscraper",
        "icon": "https://[INTERNAL]/img/pry.png",
        "mcp": {
            "url": "http://[INTERNAL]:8002/sse",
            "transport": ["sse", "streamable-http", "stdio"],
            "auth": "none",
        },
        "tools": {
            "count": len(tools),
            "items": tools,
            "by_category": {cat: len(ts) for cat, ts in categories.items()},
        },
        "categories": sorted(categories.keys()),
        "payment": {
            "x402": True,
            "crypto": ["BTC", "ETH", "SOL", "USDC", "USDT", "TRX"],
            "fiat": ["USD"],
        },
        "pricing": {
            "model": "pay_per_request",
            "free_tier": {"requests_per_minute": 10},
            "tiers": [
                {"name": "free", "price": 0, "requests_per_minute": 10},
                {"name": "pro", "price": 9, "requests_per_minute": 60, "period": "month"},
                {"name": "enterprise", "price": 49, "requests_per_minute": 300, "period": "month"},
            ],
        },
        "tags": [
            "scraping",
            "web",
            "data",
            "x402",
            "crypto",
            "ai-agents",
            "mcp",
            "cloudflare-bypass",
            "browser-automation",
            "monitoring",
            "sports-betting",
            "legal-intelligence",
            "real-estate",
            "jobs",
            "research",
        ],
        "features": [
            "15-tier anti-detection fallback",
            "x402 crypto payments (7 networks)",
            "73 MCP tools",
            "110+ scraping templates",
            "Automated signup",
            "CAPTCHA solving",
            "AI visual scraping",
            "GraphQL API discovery",
            "Mobile app API scraping",
            "Self-hosted or cloud",
        ],
        "stats": {
            "tools": len(tools),
            "categories": len(categories),
            "templates": 110,
            "tiers": 15,
            "networks": 7,
        },
    }


def generate_llms_txt() -> str:
    """Generate llms.txt for AI agent discovery (llms.txt standard)."""
    tools = get_enriched_tools()
    categories = get_tools_by_category()

    lines = [
        "# Pry Scraping API",
        "",
        "> Professional web scraping with x402 crypto payments. 15-tier anti-detection fallback, AI extraction, auto-signup, CAPTCHA solving.",
        "",
        "## Documentation",
        "",
        "- [Full Docs](https://docs.[INTERNAL])",
        "- [API Reference](https://docs.[INTERNAL]/api)",
        "- [x402 Payments](https://docs.[INTERNAL]/x402)",
        "",
        "## MCP Server",
        "",
        "- URL: http://[INTERNAL]:8002/sse",
        "- Transport: SSE, Streamable HTTP, stdio",
        "- Auth: None (public)",
        f"- Tools: {len(tools)}",
        "",
        "## Categories",
        "",
    ]
    for cat, ts in sorted(categories.items()):
        lines.append(f"- {cat}: {len(ts)} tools")

    lines.extend(
        [
            "",
            "## Tools",
            "",
        ]
    )
    for tool in sorted(tools, key=lambda t: t["name"]):
        lines.append(f"### {tool['name']}")
        lines.append("")
        lines.append(tool["description"][:200])
        lines.append("")
        lines.append(f"Category: {tool['category']}")
        lines.append("")

    return "\n".join(lines)
