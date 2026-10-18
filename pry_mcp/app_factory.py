# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Build the MCP FastAPI sub-app and wire its transport routes.

Split out of ``pry_mcp/app.py``: the factory owns construction and dependency
wiring only; handlers live in ``app_routes`` / ``app_transports``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from pry_mcp import SERVER_VERSION
from pry_mcp.app_context import (
    MCP_CORS_ORIGIN_REGEX,
    MCP_CORS_ORIGINS,
    default_get_server,
)
from pry_mcp.app_routes import mcp_json_rpc
from pry_mcp.app_transports import (
    mcp_delete_session,
    mcp_health,
    mcp_messages,
    mcp_sse,
    mcp_streamable_http_get,
)
from pry_mcp.session_store import get_session_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.responses import StreamingResponse


def create_mcp_app(get_server: Callable[[], Any] | None = None) -> FastAPI:
    """Build the MCP JSON-RPC / HTTP+SSE FastAPI sub-app.

    Args:
        get_server: Optional callable returning the MCP server instance. When
            the composition root (api.py) passes its lazy getter, tests that
            patch ``api._get_mcp_server`` keep working because the callable is
            resolved at request time. Defaults to a standalone lazy server.
    """
    app = FastAPI(
        title="Pry MCP",
        version=SERVER_VERSION,
        description="Model Context Protocol endpoints for Pry.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=MCP_CORS_ORIGINS,
        allow_origin_regex=MCP_CORS_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _get_server() -> Any:
        if get_server is not None:
            return get_server()
        return default_get_server()

    async def _store() -> Any:
        """Resolve the session store (Redis when configured, else memory)."""
        return await get_session_store()

    @app.post("/", tags=["MCP"], summary="MCP JSON-RPC endpoint (Streamable HTTP)")
    async def _json_rpc(request: Request) -> Any:
        return await mcp_json_rpc(request, _get_server, _store)

    @app.delete("/", tags=["MCP"], summary="Terminate an MCP Streamable HTTP session")
    async def _delete_session(request: Request) -> Response:
        return await mcp_delete_session(request, _store)

    @app.get("/", tags=["MCP"], summary="MCP Streamable HTTP GET (SSE)")
    async def _streamable_get(request: Request) -> Any:
        return await mcp_streamable_http_get(request, _get_server, _store)

    @app.get("/health", tags=["MCP"], summary="MCP server health")
    async def _health() -> dict[str, Any]:
        return await mcp_health(_get_server)

    @app.get("/sse", tags=["MCP"], summary="MCP HTTP+SSE transport")
    async def _sse(request: Request) -> StreamingResponse:
        return await mcp_sse(request, _get_server)

    @app.post("/messages/{session_id}", tags=["MCP"], summary="Post MCP JSON-RPC message")
    async def _messages(session_id: str, request: Request) -> Response:
        return await mcp_messages(session_id, request, _get_server)

    return app
