"""Pry - MCP fallback server: assembly.

The fallback server is three mixins composed into one object:
``ProtocolMixin`` (JSON-RPC), ``ToolMixin`` (tools) and
``ResourceMixin`` (resources/prompts). This module only assembles them.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry_mcp.constants import DEFAULT_BASE_URL
from pry_mcp.fallback_protocol import ProtocolMixin
from pry_mcp.fallback_resources import ResourceMixin
from pry_mcp.fallback_tools import ToolExecutor, ToolMixin


class FallbackMCPServer(ProtocolMixin, ToolMixin, ResourceMixin):
    """Minimal stdio JSON-RPC server used when the official SDK is absent."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Order matters: the resource handler is built over the tool registry.
        self._init_tools(tool_executor)
        self._init_resources()
        self._init_protocol()


def make_fallback_server(
    base_url: str = DEFAULT_BASE_URL,
    tool_executor: ToolExecutor | None = None,
) -> Any:
    """Build a minimal stdio JSON-RPC server if official MCP SDK not available.

    Note: the constructor arguments are forwarded to the instance — a server
    built with ``tool_executor=combined_tool_executor`` runs domain tools
    locally; without one every tool falls through to the REST proxy.
    """
    return FallbackMCPServer(base_url=base_url, tool_executor=tool_executor)
