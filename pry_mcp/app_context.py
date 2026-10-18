# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared MCP sub-app state: CORS policy, lazy server, session backing store.

Split out of ``pry_mcp/app.py`` so the route modules can share one instance of
each without importing the factory (which would be circular).
"""

from __future__ import annotations

from typing import Any

from pry_mcp import DEFAULT_BASE_URL, make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor
from pry_mcp.session_store import get_memory_store

# Same CORS allow-list the main app uses; the MCP sub-app is mounted under the
# same origin(s) and must accept the same browser clients.
MCP_CORS_ORIGINS: list[str] = [
    "https://rugmunch.io",
    # Internal app origins covered by the wildcard regex below — no
    # internal hostnames in public source (TOP-100 #11).
    "http://localhost:3000",
    "http://localhost:5173",
]
MCP_CORS_ORIGIN_REGEX: str = r"https://.*\.rugmunch\.io"

MCP_SERVER_INSTANCE: Any | None = None

# Active Streamable HTTP sessions (opaque ids issued on ``initialize``).
# Sessions are advisory: the underlying MCP server instance is shared, so a
# session id only gates stateful clients per the spec; stateless requests
# without an ``Mcp-Session-Id`` header remain fully supported.
#
# Backing store: Redis SET (shared across replicas) when ``PRY_REDIS_URL`` is
# set and reachable, else in-memory with TTL (see pry_mcp.session_store).
# ``_MCP_SESSIONS`` is that in-memory dict, kept for backward compatibility
# with tests that clear it directly.
MCP_SESSIONS: dict[str, float] = get_memory_store()._sessions


def default_get_server() -> Any:
    """Lazy-initialize a standalone spec-compliant MCP server (no api.py)."""
    global MCP_SERVER_INSTANCE
    if MCP_SERVER_INSTANCE is None:
        MCP_SERVER_INSTANCE = make_fallback_server(
            # PRY_API_URL is the REST proxy target for tools that are not
            # executed locally. In the shipped `pry-mcp` compose service the
            # API lives in a sibling container (`http://pry:8002`).
            base_url=DEFAULT_BASE_URL,
            # Crypto-market, marketplace-intelligence, and the eight data-domain
            # packages execute locally via guarded imports; other tools fall
            # through to the REST proxy.
            tool_executor=combined_tool_executor,
        )
        register_all(MCP_SERVER_INSTANCE)
    return MCP_SERVER_INSTANCE
