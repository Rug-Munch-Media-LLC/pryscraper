"""Pry — MCP FastAPI sub-app factory.

Extracted from api.py during the api-slim refactor. ``create_mcp_app()``
builds the MCP JSON-RPC / SSE FastAPI instance that api.py mounts at ``/mcp``.

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

from collections.abc import Callable
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from mcp_sse import mcp_post_message, mcp_sse_endpoint
from pry_mcp import make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor
from settings import settings

# Same CORS allow-list the main app uses; the MCP sub-app is mounted under the
# same origin(s) and must accept the same browser clients.
_MCP_CORS_ORIGINS: list[str] = [
    "https://rugmunch.io",
    "https://[INTERNAL]",
    "http://localhost:3000",
    "http://localhost:5173",
]
_MCP_CORS_ORIGIN_REGEX: str = r"https://.*\.rugmunch\.io"

_MCP_SERVER_INSTANCE: Any | None = None


def _default_get_server() -> Any:
    """Lazy-initialize a standalone spec-compliant MCP server (no api.py)."""
    global _MCP_SERVER_INSTANCE
    if _MCP_SERVER_INSTANCE is None:
        _MCP_SERVER_INSTANCE = make_fallback_server(
            base_url=f"http://localhost:{settings.port}",
            # Crypto-market and marketplace-intelligence tools
            # (pry_token_launches / pry_cex_listings / pry_token_security /
            # pry_amazon_product / pry_amazon_search / pry_walmart_product /
            # pry_tiktok_trending) execute locally via guarded imports; other
            # tools fall through to the REST proxy.
            tool_executor=combined_tool_executor,
        )
        register_all(_MCP_SERVER_INSTANCE)
    return _MCP_SERVER_INSTANCE


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
        version="3.0.0",
        description="Model Context Protocol endpoints for Pry.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_MCP_CORS_ORIGINS,
        allow_origin_regex=_MCP_CORS_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _get_server() -> Any:
        if get_server is not None:
            return get_server()
        return _default_get_server()

    @app.post("/", tags=["MCP"], summary="MCP JSON-RPC endpoint")
    async def mcp_json_rpc(request: Request) -> dict[str, Any]:
        """MCP JSON-RPC endpoint conforming to the 2024-11-05 spec."""
        body = await request.json()
        server = _get_server()
        return cast("dict[str, Any]", await server.handle_request(body))

    @app.get("/health", tags=["MCP"], summary="MCP server health")
    async def mcp_health() -> dict[str, Any]:
        """Health check for the MCP server."""
        server = _get_server()
        return {
            "status": "ok",
            "server": "pry-mcp",
            "version": "3.0.0",
            "protocol_version": "2024-11-05",
            "tools_count": len(server.tools),
            "resources_count": len(server.resources),
            "prompts_count": len(server.prompts),
        }

    @app.get("/sse", tags=["MCP"], summary="MCP HTTP+SSE transport")
    async def mcp_sse(request: Request) -> StreamingResponse:
        """MCP HTTP+SSE transport endpoint."""
        return await mcp_sse_endpoint(request, _get_server())

    @app.post(
        "/messages/{session_id}",
        tags=["MCP"],
        summary="Post MCP JSON-RPC message",
    )
    async def mcp_messages(session_id: str, request: Request) -> Response:
        """Receive a JSON-RPC message for an active MCP SSE session."""
        return await mcp_post_message(request, session_id, _get_server())

    return app
