"""Pry - MCP fallback server: JSON-RPC protocol layer.

Owns the wire protocol only: request validation, the notification rule,
the method dispatch table, the error envelope, and the stdio loop. Tool
handling lives in ``fallback_tools``; resources/prompts in
``fallback_resources``; assembly in ``fallback_factory``.

Split from fallback_server.py (470-line module + 408-line factory).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from pry_mcp.constants import (
    MCP_DISCOVER_METHOD,
    discover_result,
    negotiate_protocol_version,
    server_capabilities,
    server_info,
)
from pry_mcp.discovery import declared_protocol_version, version_rejection
from pry_mcp.notifications import (
    _attach_mcp_logging,
    set_active_mcp_server,
)

logger = logging.getLogger(__name__)

#: method name -> handler attribute name. One table, no if-chain.
METHOD_TABLE: dict[str, str] = {
    "initialize": "_rpc_initialize",
    MCP_DISCOVER_METHOD: "_rpc_discover",
    "ping": "_rpc_ping",
    "tools/list": "_rpc_tools_list",
    "tools/call": "_rpc_tools_call",
    "resources/list": "_rpc_resources_list",
    "resources/read": "_rpc_resources_read",
    "resources/subscribe": "_rpc_resources_subscribe",
    "resources/unsubscribe": "_rpc_resources_unsubscribe",
    "prompts/list": "_rpc_prompts_list",
    "prompts/get": "_rpc_prompts_get",
    "completion/complete": "_rpc_completion_complete",
    "logging/setLevel": "_rpc_logging_set_level",
}

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


class RpcError(Exception):
    """A JSON-RPC error carried out of a handler to the envelope builder."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class ProtocolMixin:
    """Request parsing, dispatch and the error envelope."""

    _initialized: bool
    _client_info: dict[str, Any]
    _mcp_log_enabled: bool
    _mcp_log_level: int

    def _init_protocol(self) -> None:
        self._initialized = False
        self._client_info = {}
        self._mcp_log_enabled = False
        self._mcp_log_level = logging.INFO

    def set_mcp_log_level(self, level_name: str) -> None:
        """Set the MCP log level (debug/info/warning/error/critical)."""
        self._mcp_log_level = _LOG_LEVELS.get(level_name.lower(), logging.INFO)
        self._mcp_log_enabled = True

    def disable_mcp_log(self) -> None:
        """Disable MCP log forwarding."""
        self._mcp_log_enabled = False

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a JSON-RPC 2.0 request.

        Notifications (requests without an ``id``) are processed for side
        effects but never produce a response, per JSON-RPC 2.0 §2.1.
        """
        if not isinstance(request, dict):
            return _error(None, -32600, "Invalid Request")
        method = request.get("method", "")
        req_id = request.get("id", 0)
        if "id" not in request:
            self._handle_notification(method)
            return None
        if not isinstance(method, str) or not method:
            return _error(req_id, -32600, "Invalid Request")
        params = request.get("params", {})
        # Modern requests declare a revision in ``_meta``; an unsupported one
        # is rejected per spec. ``initialize`` keeps legacy semantics, where an
        # unknown revision is answered with the server ceiling.
        if method != "initialize":
            rejection = version_rejection(req_id, declared_protocol_version(params))
            if rejection is not None:
                return rejection
        return await self._dispatch(method, req_id, params)

    async def _dispatch(self, method: str, req_id: Any, params: Any) -> dict[str, Any]:
        handler_name = METHOD_TABLE.get(method)
        if handler_name is None:
            return _error(req_id, -32601, f"Method not found: {method}")
        try:
            result = await getattr(self, handler_name)(params)
        except RpcError as exc:
            logger.debug("mcp_rpc_error", extra={"method": method, "code": exc.code})
            return _error(req_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_handler_failed", extra={"method": method, "error": str(exc)})
            return _error(req_id, -32603, f"Internal error: {exc}")
        return _ok(req_id, result)

    def _handle_notification(self, method: Any) -> None:
        if method == "notifications/initialized":
            self._initialized = True

    async def _rpc_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        self._initialized = True
        self._client_info = params.get("clientInfo", {})
        _attach_mcp_logging(self)
        set_active_mcp_server(self)
        return {
            "protocolVersion": negotiate_protocol_version((params or {}).get("protocolVersion")),
            "serverInfo": server_info(),
            "capabilities": server_capabilities(),
        }

    async def _rpc_discover(self, _params: dict[str, Any]) -> dict[str, Any]:
        """Modern (2026-07-28+) discovery: versions, capabilities, identity.

        Stateless and unauthenticated — a client may call it before it holds a
        session or a key, exactly like legacy ``initialize``.
        """
        return discover_result()

    async def _rpc_ping(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def _rpc_logging_set_level(self, params: dict[str, Any]) -> dict[str, Any]:
        self.set_mcp_log_level(params.get("level", "info"))
        return {}

    async def run_stdio(self) -> None:
        """Run the server over stdio (JSON-RPC 2.0)."""
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                request = json.loads(line)
                response = await self.handle_request(request)
                if response is not None:
                    _write_response(response)
            except json.JSONDecodeError as e:
                # JSON-RPC 2.0 §2.4.2: a parse error gets id null.
                logger.warning("mcp_stdin_parse_error", extra={"error": str(e)})
                _write_response(_error(None, -32700, "Parse error"))
            except (EOFError, KeyboardInterrupt):
                logger.debug("mcp_stdio_closed")
                break


def _write_response(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
