# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP JSON-RPC handler for the Streamable HTTP transport.

Split out of ``pry_mcp/app.py``: the envelope/session/auth stages live in small
helpers so each one stays under the complexity gate.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from pry.core.middleware import request_authorized
from pry_mcp.app_structured import _attach_structured_content

logger = logging.getLogger(__name__)

GetServer = Callable[[], Any]
Store = Callable[[], Awaitable[Any]]


def _rpc_error(status_code: int, body_id: Any, code: int, message: str) -> JSONResponse:
    """A JSON-RPC error envelope with the MCP-required no-store header."""
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": body_id, "error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def _read_body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Parse the request body; return a JSON-RPC error response on failure."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("suppressed %s in mcp_json_rpc: %s", type(exc).__name__, exc)
        return None, _rpc_error(200, None, -32700, "Parse error")
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
    ):
        body_id = body.get("id") if isinstance(body, dict) else None
        return None, _rpc_error(200, body_id, -32600, "Invalid Request")
    return body, None


def _authorize(request: Request, body: dict[str, Any]) -> JSONResponse | None:
    """Auth gate: tool execution requires a key or a verified x402 payment.

    Discovery methods (initialize, tools/list, resources/list, prompts/list,
    ping, health) stay public so agents can enumerate the surface without a key.
    """
    if body.get("method") != "tools/call":
        return None
    if request_authorized(request.scope):
        return None
    return _rpc_error(401, body.get("id"), -32001, "Unauthorized: tools/call requires an API key")


async def _session_headers(
    request: Request, body: dict[str, Any], store: Store
) -> tuple[dict[str, str], JSONResponse | None]:
    """Reject unknown sessions and issue one on ``initialize``."""
    headers: dict[str, str] = {"Cache-Control": "no-store"}
    session_id = request.headers.get("mcp-session-id", "")
    handle = await store()
    if session_id and not await handle.exists(session_id):
        return headers, _rpc_error(404, body.get("id"), -32001, f"Unknown session: {session_id}")
    if body.get("method") == "initialize" and not session_id:
        session_id = uuid.uuid4().hex
        await handle.add(session_id)
        headers["Mcp-Session-Id"] = session_id
    return headers, None


def _render(result: dict[str, Any], request: Request, headers: dict[str, str]) -> Response:
    """Return JSON, or a single SSE ``message`` event when the client asks."""
    if "text/event-stream" not in request.headers.get("accept", ""):
        return JSONResponse(content=result, headers=headers)
    payload = json.dumps(result)
    return StreamingResponse(
        iter([f"event: message\ndata: {payload}\n\n"]),
        media_type="text/event-stream",
        headers={
            **headers,
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def mcp_json_rpc(request: Request, get_server: GetServer, store: Store) -> Any:
    """MCP JSON-RPC endpoint implementing the Streamable HTTP transport.

    When the client advertises ``Accept: text/event-stream`` the response is
    wrapped in a single SSE ``message`` event; otherwise it is plain JSON.
    Notifications (no ``id``) are processed but answered with HTTP 202.
    """
    body, error = await _read_body(request)
    if error is not None:
        return error
    server = get_server()
    error = _authorize(request, body)
    if error is not None:
        return error
    headers, error = await _session_headers(request, body, store)
    if error is not None:
        return error
    if "id" not in body:
        await server.handle_request(body)
        return Response(status_code=202)
    result = cast("dict[str, Any] | None", await server.handle_request(body))
    if result is None:
        return Response(status_code=202)
    return _render(_attach_structured_content(result, server, body), request, headers)
