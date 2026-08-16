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

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from mcp_sse import mcp_post_message, mcp_sse_endpoint
from pry_mcp import MCP_PROTOCOL_VERSION, SERVER_VERSION, make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor
from pry_mcp.notifications import (
    register_mcp_notification_observer,
    unregister_mcp_notification_observer,
)
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
            # Crypto-market, marketplace-intelligence, and the eight data-domain
            # packages (legal / real estate / jobs / travel / attention / local /
            # gov / ip) execute locally via guarded imports; other tools fall
            # through to the REST proxy.
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
        version=SERVER_VERSION,
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

    @app.post("/", tags=["MCP"], summary="MCP JSON-RPC endpoint (Streamable HTTP)")
    async def mcp_json_rpc(request: Request) -> Any:
        """MCP JSON-RPC endpoint implementing the Streamable HTTP transport.

        Per the 2025-03-26 spec, when the client advertises
        ``Accept: text/event-stream`` the JSON-RPC response is wrapped in a
        single SSE ``message`` event; otherwise it is returned as plain JSON
        (the classic 2024-11-05 behavior, kept for backward compatibility).
        """
        body = await request.json()
        server = _get_server()
        result = cast("dict[str, Any]", await server.handle_request(body))
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            payload = json.dumps(result)
            return StreamingResponse(
                iter([f"event: message\ndata: {payload}\n\n"]),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return result

    @app.get("/", tags=["MCP"], summary="MCP Streamable HTTP GET (SSE)")
    async def mcp_streamable_http_get(request: Request) -> Any:
        """Server-initiated SSE stream for the Streamable HTTP transport.

        GET with ``Accept: text/event-stream`` opens a stream that forwards
        MCP notifications (resources/updated, tools/list_changed, log
        messages) to the client with periodic keepalive comments. Without the
        SSE Accept header the endpoint returns 406 Not Acceptable per the
        spec (a client performing GET without SSE intent has nothing to do).
        """
        if "text/event-stream" not in request.headers.get("accept", ""):
            return JSONResponse(
                status_code=406,
                content={"detail": "Accept: text/event-stream is required for GET"},
            )
        # Force lazy server init so notifications have a server to observe.
        _get_server()
        queue: asyncio.Queue[str] = asyncio.Queue()

        def observer(notification: dict[str, Any]) -> None:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(f"event: message\ndata: {json.dumps(notification)}\n\n")

        register_mcp_notification_observer(observer)

        async def event_stream() -> AsyncIterator[str]:
            try:
                while True:
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError:
                        yield ": ping\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                unregister_mcp_notification_observer(observer)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/health", tags=["MCP"], summary="MCP server health")
    async def mcp_health() -> dict[str, Any]:
        """Health check for the MCP server."""
        server = _get_server()
        return {
            "status": "ok",
            "server": "pry-mcp",
            "version": SERVER_VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "transports": ["stdio", "streamable-http", "http-sse"],
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
