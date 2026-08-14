"""Pry — AI Agent Plugin.
OpenAPI spec server, MCP server wrapper, and GPT Action helper."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


def get_openapi_spec() -> dict[str, Any]:
    """Get the OpenAPI spec for AI agent integration.

    Serves the LIVE spec generated from the running FastAPI app so the
    AI-consumer surface (GPT Actions, MCP configs) can never drift from
    the actual registered routes. The checked-in openapi.json is NOT read
    here — it exists only as a static snapshot for tooling/CI.
    """
    try:
        # Lazy import: `api` is heavy and importing it at module load would
        # couple this lightweight plugin to the full app (and risk a circular
        # import since routers/ai.py and routers/system.py import this module).
        from api import app

        return cast("dict[str, Any]", app.openapi())
    except Exception as e:  # noqa: BLE001
        logger.error("openapi_spec_generation_failed", extra={"error": str(e)})
        return {"error": "OpenAPI spec not found"}


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
        "contact_email": "support@pry.dev",
        "legal_info_url": "https://pry.dev/terms",
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
