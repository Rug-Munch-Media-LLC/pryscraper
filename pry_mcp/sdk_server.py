"""Pry - MCP SDK server implementation.

Uses the official MCP Python SDK when available.
Contains create_server(), register_all(), and main().

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from pry_mcp.constants import SERVER_NAME, SERVER_VERSION
from pry_mcp.fallback_server import combined_tool_executor, make_fallback_server
from pry_mcp.resources import PRY_PROMPTS, PRY_RESOURCES
from pry_mcp.tools import PRY_TOOLS

logger = logging.getLogger(__name__)

# Try to import official MCP SDK
try:
    import mcp.server.session  # noqa: F401
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (  # noqa: F401
        Annotations,
        BlobResourceContents,
        CallToolRequest,
        CallToolResult,
        CompleteResult,
        Completion,
        CompletionArgument,
        CompletionContext,
        EmptyResult,
        GetPromptResult,
        ImageContent,
        ListPromptsResult,
        ListResourcesResult,
        ListToolsResult,
        LoggingLevel,
        PaginatedRequest,
        ReadResourceRequest,
        ReadResourceResult,
        Resource,
        ServerResult,
        TextContent,
        TextResourceContents,
        Tool,
    )

    _has_mcp_sdk = True
except ImportError:
    _has_mcp_sdk = False


def create_server() -> Any:
    """Create the MCP server (uses official SDK if available, fallback otherwise)."""
    if _has_mcp_sdk:
        # TODO: register tools/resources/prompts using official SDK decorators
        # and return the SDK server when tool registration is complete.
        Server(SERVER_NAME, SERVER_VERSION)
    # Crypto-market and marketplace-intelligence tools (pry_token_launches /
    # pry_cex_listings / pry_token_security / pry_amazon_product /
    # pry_amazon_search / pry_walmart_product / pry_tiktok_trending) execute
    # locally via guarded imports; other tools fall through to the REST proxy.
    return make_fallback_server(tool_executor=combined_tool_executor)


def register_all(server: Any) -> None:
    """Register all Pry tools, resources, and prompts."""
    for tool in PRY_TOOLS:
        server.register_tool(tool["name"], tool)
    for resource in PRY_RESOURCES:
        server.register_resource(resource["uri"], resource)
    for prompt in PRY_PROMPTS:
        server.register_prompt(prompt["name"], prompt)


async def main() -> None:
    """Run the MCP server."""
    server = create_server()
    register_all(server)
    if _has_mcp_sdk:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    else:
        await server.run_stdio()
