# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP transport endpoints: session DELETE, SSE GET, health, HTTP+SSE.

Split out of ``pry_mcp/app.py``; ``app_factory`` wires these onto the sub-app.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from pry.api.mcp_sse import mcp_post_message, mcp_sse_endpoint
from pry_mcp import MCP_PROTOCOL_VERSION, SERVER_VERSION
from pry_mcp.notifications import (
    register_mcp_notification_observer,
    unregister_mcp_notification_observer,
)

logger = logging.getLogger(__name__)

GetServer = Callable[[], Any]
Store = Callable[[], Awaitable[Any]]

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def mcp_delete_session(request: Request, store: Store) -> Response:
    """Terminate the session named by the ``Mcp-Session-Id`` header."""
    session_id = request.headers.get("mcp-session-id", "")
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Mcp-Session-Id header required for DELETE"},
        )
    handle = await store()
    if not await handle.exists(session_id):
        return JSONResponse(status_code=404, content={"detail": "Unknown session"})
    await handle.remove(session_id)
    return Response(status_code=200)


def _close_after(request: Request) -> int:
    """Test hook: close the SSE stream after one keepalive."""
    try:
        return int(request.query_params.get("_sse_test_close_after", "0"))
    except ValueError as exc:
        logger.warning("suppressed ValueError in mcp_streamable_http_get: %s", exc)
        return 0


async def _event_stream(
    queue: asyncio.Queue[str],
    observer: Callable[[dict[str, Any]], None],
    close_after: int,
) -> AsyncIterator[str]:
    try:
        if close_after > 0:
            yield ": ping\n\n"
            return
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=30.0)
            except TimeoutError as exc:
                logger.warning("suppressed TimeoutError in mcp_streamable_http_get: %s", exc)
                yield ": ping\n\n"
    except asyncio.CancelledError as exc:
        logger.warning("suppressed asyncio.CancelledError in mcp_streamable_http_get: %s", exc)
    finally:
        unregister_mcp_notification_observer(observer)


async def mcp_streamable_http_get(request: Request, get_server: GetServer, store: Store) -> Any:
    """Server-initiated SSE stream forwarding MCP notifications to the client.

    GET without ``Accept: text/event-stream`` is 406: a client performing GET
    without SSE intent has nothing to do.
    """
    if "text/event-stream" not in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=406,
            content={"detail": "Accept: text/event-stream is required for GET"},
        )
    session_id = request.headers.get("mcp-session-id", "")
    if session_id and not await (await store()).exists(session_id):
        return JSONResponse(
            status_code=404,
            content={"detail": f"Unknown session: {session_id}"},
        )
    # Force lazy server init so notifications have a server to observe.
    get_server()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def observer(notification: dict[str, Any]) -> None:
        with suppress(asyncio.QueueFull):
            queue.put_nowait(f"event: message\ndata: {json.dumps(notification)}\n\n")

    register_mcp_notification_observer(observer)
    return StreamingResponse(
        _event_stream(queue, observer, _close_after(request)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


async def mcp_health(get_server: GetServer) -> dict[str, Any]:
    """Health check for the MCP server."""
    server = get_server()
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


async def mcp_sse(request: Request, get_server: GetServer) -> StreamingResponse:
    """MCP HTTP+SSE transport endpoint."""
    return await mcp_sse_endpoint(request, get_server())


async def mcp_messages(session_id: str, request: Request, get_server: GetServer) -> Response:
    """Receive a JSON-RPC message for an active MCP SSE session."""
    return await mcp_post_message(request, session_id, get_server())
