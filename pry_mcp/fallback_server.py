"""Pry - MCP fallback server (facade).

Implements the MCP protocol when the official MCP SDK is not available.
Thin re-export facade. Implementation lives in:

- ``pry_mcp.fallback_protocol``  — JSON-RPC envelope, dispatch table, stdio
- ``pry_mcp.fallback_tools``     — tools/list, tools/call, REST proxy
- ``pry_mcp.fallback_resources`` — resources/prompts/completions
- ``pry_mcp.fallback_factory``   — assembly + ``make_fallback_server()``

Split from mcp_production.py; then split again into the modules above so no
module owns more than one responsibility.

The re-exports below are deliberate back-compat seams: callers patch
``pry_mcp.fallback_server.get_client`` / ``.httpx`` and import the tool
dispatch symbols from here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import httpx as httpx  # re-export: tests patch this module for the REST proxy

from pry.core.client import get_client as get_client  # re-export: patch seam
from pry_mcp.fallback_factory import FallbackMCPServer, make_fallback_server
from pry_mcp.tool_registry import (
    ToolRegistry,
    _hot_tool_cache,
    _ToolNotHandled,
    combined_tool_executor,
)

__all__ = [
    "FallbackMCPServer",
    "ToolRegistry",
    "_ToolNotHandled",
    "_hot_tool_cache",
    "combined_tool_executor",
    "get_client",
    "httpx",
    "make_fallback_server",
]
