"""Pry - Production MCP Server (backward-compatibility shim).

The real implementation has been split into the pry_mcp/ sub-package.
Import from pry_mcp for new code; this module re-exports the public API.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry_mcp import (
    DEFAULT_BASE_URL,
    MCP_PROTOCOL_VERSION,
    PRY_PROMPTS,
    PRY_RESOURCES,
    PRY_TOOLS,
    SERVER_NAME,
    SERVER_VERSION,
    MCPLoggingHandler,
    create_server,
    main,
    make_fallback_server,
    notify_resource_changed,
    notify_resource_list_changed,
    notify_tool_list_changed,
    register_all,
    register_mcp_notification_observer,
    set_active_mcp_server,
    unregister_mcp_notification_observer,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "MCP_PROTOCOL_VERSION",
    "PRY_PROMPTS",
    "PRY_RESOURCES",
    "PRY_TOOLS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "MCPLoggingHandler",
    "create_server",
    "main",
    "make_fallback_server",
    "make_fallback_server",
    "notify_resource_changed",
    "notify_resource_list_changed",
    "notify_tool_list_changed",
    "register_all",
    "register_mcp_notification_observer",
    "set_active_mcp_server",
    "unregister_mcp_notification_observer",
]

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
