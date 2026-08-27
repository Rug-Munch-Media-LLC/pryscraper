"""Pry — AI router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI"])


@router.get("/v1/ai/gpt-manifest", tags=["AI"], summary="Get GPT Action manifest for ChatGPT")
async def get_gpt_manifest() -> JSONResponse:
    """Get the GPT Action manifest for ChatGPT integration.

    Add this to your GPT configuration in ChatGPT to give it
    web scraping capabilities through Pry.
    """
    from pry.api.ai_plugin import get_gpt_action_manifest

    return JSONResponse(content=get_gpt_action_manifest())


@router.get("/v1/ai/mcp-config", tags=["AI"], summary="Get MCP server config for Claude/Cursor")
async def get_mcp_config() -> JSONResponse:
    """Get the MCP server configuration for Claude/Cursor.

    Add this to your AI tool's MCP configuration file to let
    Claude and Cursor scrape the web through Pry.
    """
    from pry.api.ai_plugin import get_mcp_server_config

    return JSONResponse(content={"success": True, "data": get_mcp_server_config()})
