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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Static view: real SDK types so pyright validates constructor kwargs.
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        ReadResourceResult,
        Resource,
        TextContent,
        TextResourceContents,
        Tool,
    )
from pry_mcp.fallback_server import combined_tool_executor, make_fallback_server
from pry_mcp.resources import PRY_PROMPTS, PRY_RESOURCES
from pry_mcp.tools import PRY_TOOLS

logger = logging.getLogger(__name__)

# Try to import official MCP SDK
try:
    import mcp.server.session  # noqa: F401
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
except ImportError as e:
    logger.warning(
        "suppressed %s in <module> (sdk_server.py:70): %s",
        "ImportError",
        e,
    )
    _has_mcp_sdk = False


from pry_mcp.sdk_server_build import build_sdk_server as _create_sdk_server


def _sdk_supports_modern_discovery() -> bool:
    """True only when the installed SDK can dispatch ``server/discover``.

    SDK 1.x owns the decorator-based ``Server`` API but has no modern
    discovery types; serving stdio through it would silently downgrade a
    modern-only session to the legacy era (``server/discover`` -> method not
    found). Only an SDK that ships the 2026-07-28 request types is eligible;
    every other version falls through to Pry's dual-era JSON-RPC loop, which
    answers ``server/discover`` and legacy ``initialize`` from one surface.
    """
    try:
        import mcp.types as mcp_types
    except ImportError:
        return False
    return hasattr(mcp_types, "DiscoverRequest")


def create_server() -> Any:
    """Create the MCP server (uses official SDK if available, fallback otherwise).

    The SDK is used only when it can serve the modern era; otherwise the
    fallback server runs a dual-era JSON-RPC loop over stdio, so both
    ``initialize`` and ``server/discover`` work on every shipped entry point.
    """
    if _has_mcp_sdk and _sdk_supports_modern_discovery():
        try:
            return _create_sdk_server()
        except AttributeError as exc:
            # MCP SDK >=2.0 removed the decorator API — fall back to the
            # built-in server (same tools/resources/prompts over stdio).
            logger.warning("mcp_sdk_server_unavailable: %s", exc)
    # Crypto-market and marketplace-intelligence tools (pry_token_launches /
    # pry_cex_listings / pry_token_security / pry_amazon_product /
    # pry_amazon_search / pry_walmart_product / pry_tiktok_trending) execute
    # locally via guarded imports; other tools fall through to the REST proxy.
    return make_fallback_server(tool_executor=combined_tool_executor)


def register_all(server: Any) -> None:
    """Register all Pry tools, resources, and prompts.

    No-op for SDK servers (their handlers are registered at construction in
    ``_create_sdk_server``); duck-typed registration for the fallback server.
    """
    if getattr(server, "_pry_sdk_registered", False):
        return
    for tool in PRY_TOOLS:
        server.register_tool(tool["name"], tool)
    for resource in PRY_RESOURCES:
        server.register_resource(resource["uri"], resource)
    for prompt in PRY_PROMPTS:
        server.register_prompt(prompt["name"], prompt)


async def main() -> None:
    """Run the MCP server.

    Uses the official SDK over stdio when available; otherwise the built-in
    fallback stdio server. ``create_server()`` returns whichever matches, so
    this only needs to detect which one it got.
    """
    server = create_server()
    register_all(server)
    if _has_mcp_sdk and hasattr(server, "run") and hasattr(server, "create_initialization_options"):
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    else:
        await server.run_stdio()
