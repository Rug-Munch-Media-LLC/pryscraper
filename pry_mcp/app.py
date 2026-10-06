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
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from pry.api.mcp_sse import mcp_post_message, mcp_sse_endpoint
from pry.core.middleware import request_authorized
from pry.core.settings import settings
from pry_mcp import MCP_PROTOCOL_VERSION, SERVER_VERSION, make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor
from pry_mcp.notifications import (
    register_mcp_notification_observer,
    unregister_mcp_notification_observer,
)
from pry_mcp.session_store import get_memory_store, get_session_store

logger = logging.getLogger(__name__)

# Same CORS allow-list the main app uses; the MCP sub-app is mounted under the
# same origin(s) and must accept the same browser clients.
_MCP_CORS_ORIGINS: list[str] = [
    "https://rugmunch.io",
    # Internal app origins covered by the wildcard regex below — no
    # internal hostnames in public source (TOP-100 #11).
    "http://localhost:3000",
    "http://localhost:5173",
]
_MCP_CORS_ORIGIN_REGEX: str = r"https://.*\.rugmunch\.io"

_MCP_SERVER_INSTANCE: Any | None = None

# Active Streamable HTTP sessions (opaque ids issued on ``initialize``).
# Sessions are advisory: the underlying MCP server instance is shared, so a
# session id only gates stateful clients per the spec; stateless requests
# without an ``Mcp-Session-Id`` header remain fully supported and are the
# default for one-shot integrations.
#
# Backing store: Redis SET (shared across replicas) when ``PRY_REDIS_URL``
# is set and reachable, else in-memory with TTL (see pry_mcp.session_store).
# ``_MCP_SESSIONS`` is kept as the in-memory store's backing dict for
# backward compatibility with tests that clear it directly.
_MCP_SESSIONS: dict[str, float] = get_memory_store()._sessions


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

    async def _store() -> Any:
        """Resolve the session store (Redis when configured, else memory)."""
        return await get_session_store()

    @app.post("/", tags=["MCP"], summary="MCP JSON-RPC endpoint (Streamable HTTP)")
    async def mcp_json_rpc(request: Request) -> Any:
        """MCP JSON-RPC endpoint implementing the Streamable HTTP transport.

        Per the 2025-03-26 spec, when the client advertises
        ``Accept: text/event-stream`` the JSON-RPC response is wrapped in a
        single SSE ``message`` event; otherwise it is returned as plain JSON
        (the classic 2024-11-05 behavior, kept for backward compatibility).

        Compliance details:
        * malformed JSON → JSON-RPC ``-32700`` parse error;
        * non-JSON-RPC payloads → JSON-RPC ``-32600`` invalid request;
        * unknown ``Mcp-Session-Id`` → HTTP 404 (Streamable HTTP §6.2);
        * ``initialize`` without a session id → a fresh ``Mcp-Session-Id``
          response header is issued;
        * notifications (no ``id``) are processed but answered with HTTP 202
          and an empty body, never a JSON-RPC response;
        * responses carry ``Cache-Control: no-store`` per the spec.
        """
        # 1. Parse the body — JSON-RPC -32700 on malformed JSON.
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "suppressed %s in create_mcp_app (app.py:139): %s",
                "(json.JSONDecodeError, ValueError)",
                e,
            )
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                headers={"Cache-Control": "no-store"},
            )

        # 2. Validate it is a JSON-RPC request object — -32600 otherwise.
        if (
            not isinstance(body, dict)
            or body.get("jsonrpc") != "2.0"
            or not isinstance(body.get("method"), str)
        ):
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id") if isinstance(body, dict) else None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
                headers={"Cache-Control": "no-store"},
            )

        server = _get_server()

        # 3. Auth gate: tool execution is a paid/arbitrary-code operation and
        #    requires a valid API key (Bearer PRY_API_KEY / pry_ key / JWT) or
        #    a verified x402 payment. Discovery methods (initialize,
        #    tools/list, resources/list, prompts/list, ping, health) stay
        #    public so agents can enumerate the surface without a key.
        if body.get("method") == "tools/call" and not request_authorized(request.scope):
            return JSONResponse(
                status_code=401,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {
                        "code": -32001,
                        "message": "Unauthorized: tools/call requires an API key",
                    },
                },
                headers={"Cache-Control": "no-store"},
            )

        # 4. Session management: reject unknown inbound sessions; issue a new
        session_id = request.headers.get("mcp-session-id", "")
        if session_id and not await (await _store()).exists(session_id):
            return JSONResponse(
                status_code=404,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32001, "message": f"Unknown session: {session_id}"},
                },
                headers={"Cache-Control": "no-store"},
            )
        response_headers: dict[str, str] = {"Cache-Control": "no-store"}
        if body.get("method") == "initialize" and not session_id:
            session_id = uuid.uuid4().hex
            await (await _store()).add(session_id)
            response_headers["Mcp-Session-Id"] = session_id

        # 5. Notifications (requests without id) never produce a response.
        if "id" not in body:
            await server.handle_request(body)
            return Response(status_code=202)

        result = cast("dict[str, Any] | None", await server.handle_request(body))
        if result is None:
            return Response(status_code=202)

        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            payload = json.dumps(result)
            return StreamingResponse(
                iter([f"event: message\ndata: {payload}\n\n"]),
                media_type="text/event-stream",
                headers={
                    **response_headers,
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return JSONResponse(content=result, headers=response_headers)

    @app.delete("/", tags=["MCP"], summary="Terminate an MCP Streamable HTTP session")
    async def mcp_delete_session(request: Request) -> Response:
        """Terminate the session named by the ``Mcp-Session-Id`` header.

        Streamable HTTP allows a client to delete a session it no longer
        needs; the server forgets the id and any later request using it is
        answered with 404.
        """
        session_id = request.headers.get("mcp-session-id", "")
        if not session_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "Mcp-Session-Id header required for DELETE"},
            )
        if not await (await _store()).exists(session_id):
            return JSONResponse(status_code=404, content={"detail": "Unknown session"})
        await (await _store()).remove(session_id)
        return Response(status_code=200)

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
        session_id = request.headers.get("mcp-session-id", "")
        if session_id and not await (await _store()).exists(session_id):
            return JSONResponse(
                status_code=404,
                content={"detail": f"Unknown session: {session_id}"},
            )
        # Force lazy server init so notifications have a server to observe.
        _get_server()
        queue: asyncio.Queue[str] = asyncio.Queue()

        def observer(notification: dict[str, Any]) -> None:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(f"event: message\ndata: {json.dumps(notification)}\n\n")

        register_mcp_notification_observer(observer)

        # Private test hook (same convention as mcp_sse.py): close the stream
        # after a keepalive so ASGITransport-based tests can read the response
        # without hanging on the infinite stream.
        try:
            _test_close_after = int(request.query_params.get("_sse_test_close_after", "0"))
        except ValueError as e:
            logger.warning(
                "suppressed %s in create_mcp_app (app.py:284): %s",
                "ValueError",
                e,
            )
            _test_close_after = 0

        async def event_stream() -> AsyncIterator[str]:
            try:
                if _test_close_after > 0:
                    yield ": ping\n\n"
                    return
                while True:
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError as e:
                        logger.warning(
                            "suppressed %s in create_mcp_app (app.py:295): %s",
                            "TimeoutError",
                            e,
                        )
                        yield ": ping\n\n"
            except asyncio.CancelledError as e:
                logger.warning(
                    "suppressed %s in create_mcp_app (app.py:297): %s",
                    "asyncio.CancelledError",
                    e,
                )
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
