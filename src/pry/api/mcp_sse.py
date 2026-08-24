"""Pry — MCP HTTP+SSE transport server.

Implements the official Model Context Protocol HTTP+SSE transport:
  1. Client connects to GET /mcp/sse
  2. Server sends an `endpoint` event with a POST URL (e.g., /mcp/messages/{session_id})
  3. Client POSTs JSON-RPC messages to that URL
  4. Server replies by enqueueing JSON-RPC responses as `message` events on the SSE stream

Session state is kept in memory. For production multi-worker deployments, use a
Redis-backed queue or sticky sessions.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from pry_mcp import (
    register_mcp_notification_observer,
    unregister_mcp_notification_observer,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)

# In-memory session store. Maps session_id -> outbound message queue.
MCP_SSE_SESSIONS: dict[str, asyncio.Queue[str]] = {}
MCP_SSE_TASKS: dict[str, asyncio.Task[Any]] = {}

SESSION_TTL_SECONDS = 300  # cleanup idle sessions after 5 minutes


def _new_session_id() -> str:
    """Generate a cryptographically random session ID."""
    return secrets.token_urlsafe(16)


def _create_event(event: str, data: str) -> str:
    """Format a server-sent event per the SSE spec."""
    return f"event: {event}\ndata: {data}\n\n"


def _get_or_create_queue(session_id: str) -> asyncio.Queue[str]:
    """Return the outbound SSE queue for a session, creating if necessary."""
    if session_id not in MCP_SSE_SESSIONS:
        MCP_SSE_SESSIONS[session_id] = asyncio.Queue()
    return MCP_SSE_SESSIONS[session_id]


def _enqueue_response(session_id: str, response: dict[str, Any]) -> None:
    """Enqueue a JSON-RPC response to be sent on the SSE stream."""
    queue = MCP_SSE_SESSIONS.get(session_id)
    if queue is None:
        logger.warning("mcp_sse_session_not_found", extra={"session_id": session_id})
        return
    try:
        queue.put_nowait(_create_event("message", json.dumps(response)))
    except asyncio.QueueFull:
        logger.warning("mcp_sse_queue_full", extra={"session_id": session_id})


def _cleanup_session(
    session_id: str, observer: Callable[[dict[str, Any]], None] | None = None
) -> None:
    """Remove session state and cancel any keepalive task."""
    MCP_SSE_SESSIONS.pop(session_id, None)
    task = MCP_SSE_TASKS.pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()
    if observer is not None:
        try:
            unregister_mcp_notification_observer(observer)
        except Exception as e:  # noqa: BLE001
            logger.warning("mcp_sse_unregister_observer_failed", extra={"error": str(e)})


async def _keepalive_loop(session_id: str) -> None:
    """Send periodic comment keepalives to keep proxies/NATs happy."""
    queue = _get_or_create_queue(session_id)
    try:
        while True:
            await asyncio.sleep(30)
            queue.put_nowait(": ping\n\n")
    except asyncio.CancelledError:
        pass  # cancellation is control flow, not failure
    except Exception as e:  # noqa: BLE001
        logger.warning("mcp_sse_keepalive_error", extra={"session_id": session_id, "error": str(e)})


async def mcp_sse_endpoint(
    request: Request,
    message_handler: Any,
) -> StreamingResponse:
    """SSE endpoint for MCP clients.

    Args:
        request: FastAPI request object (used to build the post-back URL).
        message_handler: An object with an async `handle_request` method.
    """
    session_id = _new_session_id()
    queue = _get_or_create_queue(session_id)

    # Build the post-back URL. Prefer absolute URL from request headers if available.
    base_url = str(request.base_url).rstrip("/")
    post_url = f"{base_url}/mcp/messages/{session_id}"

    # Prepare the endpoint event. It is yielded directly so the client gets it
    # immediately without waiting on the outbound queue.
    endpoint_event = _create_event("endpoint", post_url)

    # Register a global notification observer so this session receives
    # resources/updated, resources/list_changed, tools/list_changed, and log messages.
    def observer(notification: dict[str, Any]) -> None:
        _enqueue_response(session_id, notification)

    register_mcp_notification_observer(observer)

    # Start keepalive task.
    keepalive_task = asyncio.create_task(_keepalive_loop(session_id))
    MCP_SSE_TASKS[session_id] = keepalive_task

    last_activity = time.time()

    # Private test hook: close the SSE stream after N message events (not counting
    # the endpoint event). httpx's ASGITransport cannot consume an infinite
    # streaming response in tests, so this lets integration tests verify the
    # round-trip without hanging.
    try:
        _test_close_after = int(request.query_params.get("_sse_test_close_after", "0"))
    except ValueError:
        _test_close_after = 0

    async def event_stream() -> AsyncIterator[str]:
        nonlocal last_activity
        messages_yielded = 0
        try:
            # Yield the endpoint event first to unblock the client immediately.
            yield endpoint_event
            while True:
                # Wait for outbound messages with a timeout so we can enforce TTL.
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    last_activity = time.time()
                    yield event
                    if _test_close_after > 0:
                        messages_yielded += 1
                        if messages_yielded >= _test_close_after:
                            break
                except TimeoutError:
                    if time.time() - last_activity > SESSION_TTL_SECONDS:
                        yield _create_event(
                            "error",
                            json.dumps({"error": "session_idle_timeout"}),
                        )
                        break
                    continue
        except asyncio.CancelledError:
            pass  # cancellation is control flow, not failure
        finally:
            _cleanup_session(session_id, observer)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


async def mcp_post_message(
    request: Request,
    session_id: str,
    message_handler: Any,
) -> Response:
    """Receive a JSON-RPC message from an MCP client and enqueue the response.

    Returns HTTP 202 Accepted immediately; the actual JSON-RPC response is sent
    over the SSE stream associated with session_id.
    """
    if session_id not in MCP_SSE_SESSIONS:
        raise HTTPException(status_code=404, detail="MCP SSE session not found")

    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        _enqueue_response(
            session_id,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            },
        )
        return Response(status_code=202)

    # Handle initialize specially: it should not have an id response? Actually initialize does have id.
    response = await message_handler.handle_request(body)
    if response is not None:
        _enqueue_response(session_id, response)

    return Response(status_code=202)
