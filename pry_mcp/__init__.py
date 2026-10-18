"""Pry - MCP server sub-package.

Split from mcp_production.py for maintainability.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry_mcp.constants import (
    DEFAULT_BASE_URL,
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    negotiate_protocol_version,
)
from pry_mcp.fallback_server import make_fallback_server
from pry_mcp.notifications import (
    MCPLoggingHandler,
    notify_resource_changed,
    notify_resource_list_changed,
    notify_tool_list_changed,
    register_mcp_notification_observer,
    set_active_mcp_server,
    unregister_mcp_notification_observer,
)
from pry_mcp.resources import PRY_PROMPTS, PRY_RESOURCES
from pry_mcp.sdk_server import create_server, main, register_all
from pry_mcp.tools import PRY_TOOLS

__all__ = [
    "DEFAULT_BASE_URL",
    "MCP_PROTOCOL_VERSION",
    "PRY_PROMPTS",
    "PRY_RESOURCES",
    "PRY_TOOLS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "MCPLoggingHandler",
    "create_server",
    "main",
    "make_fallback_server",
    "negotiate_protocol_version",
    "notify_resource_changed",
    "notify_resource_list_changed",
    "notify_tool_list_changed",
    "register_all",
    "register_mcp_notification_observer",
    "set_active_mcp_server",
    "unregister_mcp_notification_observer",
]
