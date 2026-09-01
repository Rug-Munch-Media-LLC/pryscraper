"""Pry — AI Agent Plugin.
GPT Action helper and MCP server wrapper.

The OpenAPI spec generator lives in :mod:`pry.api.openapi_spec` — it needs
the full FastAPI app (all domains) and must not be importable from domain
routers, or the domain-independence contract sees routers.ai -> api monolith
-> every other domain.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_gpt_action_manifest() -> dict[str, Any]:
    """Get the GPT Action manifest for ChatGPT integration.

    This manifest configures ChatGPT to use Pry as a custom GPT Action.
    """
    return {
        "schema_version": "v1",
        "name_for_human": "Pry Web Scraper",
        "name_for_model": "pry_scraper",
        "description_for_human": "Scrape, crawl, and extract data from any website. Get clean markdown, structured JSON, and monitor changes.",
        "description_for_model": "Plugin for scraping websites. Use it to extract content from URLs, crawl sites, extract structured data with CSS selectors, check legal compliance, monitor changes, and more.",
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": "/openapi.json"},
        "contact_email": "support@pryscraper.com",
        "legal_info_url": "https://pryscraper.com/terms",
    }


def get_mcp_server_config() -> dict[str, Any]:
    """Get the MCP server config for Claude/Cursor integration.

    This can be added to the AI tool's MCP configuration.
    """
    return {
        "pry_scraper": {
            "type": "local",
            "command": ["python3", "-m", "mcp_server"],
            "description": "Scrape, crawl, and extract data from any website",
            "enabled": True,
        }
    }
