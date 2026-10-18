"""Pry — MCP FastAPI sub-app factory (re-export facade).

Extracted from api.py during the api-slim refactor. ``create_mcp_app()``
builds the MCP JSON-RPC / SSE FastAPI instance that api.py mounts at ``/mcp``.

Split into focused modules during the mcp-app refactor; this module keeps the
historic import surface (``pry_mcp.app.<name>``) so callers and tests that
patch these symbols keep working:

* ``app_context``    — CORS policy, lazy server, session backing store
* ``app_structured`` — ``structuredContent`` rehydration for ``tools/call``
* ``app_routes``     — the JSON-RPC / Streamable HTTP handler
* ``app_transports`` — session DELETE, SSE GET, health, HTTP+SSE
* ``app_factory``    — ``create_mcp_app`` construction + route wiring

The MCP server itself stays lazy and is owned by the composition root
(``api._get_mcp_server``) so tests that patch ``api._get_mcp_server`` keep
working. Pass ``get_server`` to supply a callable returning the server; when
omitted, a standalone lazy fallback server is created on first use.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry_mcp.app_context import (
    MCP_CORS_ORIGIN_REGEX as _MCP_CORS_ORIGIN_REGEX,
    MCP_CORS_ORIGINS as _MCP_CORS_ORIGINS,
    MCP_SESSIONS as _MCP_SESSIONS,
    default_get_server as _default_get_server,
)
from pry_mcp.app_factory import create_mcp_app
from pry_mcp.app_routes import mcp_json_rpc
from pry_mcp.app_structured import _attach_structured_content

__all__ = [
    "_MCP_CORS_ORIGINS",
    "_MCP_CORS_ORIGIN_REGEX",
    "_MCP_SESSIONS",
    "_attach_structured_content",
    "_default_get_server",
    "create_mcp_app",
    "mcp_json_rpc",
]
