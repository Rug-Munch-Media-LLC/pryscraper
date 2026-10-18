"""Pry - MCP fallback server: tools surface and execution.

Owns ``tools/list`` and ``tools/call``: local executor dispatch, the REST
proxy fallback, and normalisation of any result into an MCP content array.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from pry_mcp.fallback_protocol import RpcError
from pry_mcp.tool_registry import (
    ToolRegistry,
    _ToolNotHandled,
    register_standard_executors,
)
from pry_mcp.tool_routes import TOOL_ROUTES

logger = logging.getLogger(__name__)

#: Sentinel: the local chain declined, so the REST proxy must run.
UNHANDLED = object()

ToolExecutor = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


def _facade() -> Any:
    """Resolve the facade module lazily.

    Back-compat seam: tests patch ``pry_mcp.fallback_server.get_client`` and
    ``pry_mcp.fallback_server.httpx``, so the proxy must read those names off
    the facade at call time rather than binding them on import.
    """
    from pry_mcp import fallback_server

    return fallback_server


def _tool_error(message: str, code: str) -> dict[str, Any]:
    """Structured MCP tool error (isError=True, JSON text payload)."""
    return {
        "content": [{"type": "text", "text": json.dumps({"error": message, "code": code})}],
        "isError": True,
    }


class ToolMixin:
    """Tool registration, dispatch and the REST proxy."""

    base_url: str
    tools: dict[str, dict[str, Any]]
    tool_executor: ToolExecutor | None
    _registry: ToolRegistry

    def _init_tools(self, tool_executor: ToolExecutor | None) -> None:
        self.tools = {}
        self.tool_executor = tool_executor
        # Standard local chain registered by default; a custom executor wins.
        self._registry = register_standard_executors(ToolRegistry())

    def register_tool(self, name: str, definition: dict[str, Any]) -> None:
        self.tools[name] = definition

    def list_tools(self) -> dict[str, Any]:
        return {"tools": list(self.tools.values())}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool. Returns a proper MCP-compliant response."""
        if name not in self.tools:
            return {"error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        result = await self._run_local(name, arguments)
        if result is UNHANDLED:
            return await self._proxy_tool(name, arguments)
        return result

    async def _run_local(self, name: str, arguments: dict[str, Any]) -> Any:
        """Run the local chain; ``UNHANDLED`` means fall through to the proxy."""
        executor = self.tool_executor or self._registry.dispatch
        try:
            result = await executor(name, arguments)
        except _ToolNotHandled as exc:
            logger.warning("tool_not_handled", extra={"tool": name, "error": str(exc)})
            return UNHANDLED
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_tool_executor_failed", extra={"tool": name, "error": str(exc)})
            return _tool_error(f"Tool {name} failed: {exc}", "TOOL_EXECUTION_FAILED")
        return self._tool_result_to_content(result, name)

    async def _proxy_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the Pry API for a REST-routed tool."""
        if name not in TOOL_ROUTES:
            return _tool_error(f"Tool {name} not yet wired to API", "TOOL_NOT_WIRED")
        method, path = TOOL_ROUTES[name]
        # Server-to-server auth: without the key the x402 gate 402s its own
        # tools (402-challenge loop).
        api_key = os.getenv("PRY_API_KEY", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body = {"timeout": 60, "headers": headers}
        body["params" if method == "GET" else "json"] = arguments
        try:
            client = await _facade().get_client()
            response = await client.request(method, f"{self.base_url}{path}", **body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            logger.warning("mcp_tool_api_call_failed", extra={"tool": name, "error": str(exc)})
            message = (
                f"Would call {method} {path} with {arguments}. Live execution unavailable: {exc}"
            )
            return _tool_error(message, "API_UNAVAILABLE")
        return self._tool_result_to_content(data, name)

    def _tool_result_to_content(self, result: Any, tool_name: str) -> dict[str, Any]:
        """Normalize a tool result into an MCP content array."""
        if isinstance(result, dict):
            if "content" in result and isinstance(result["content"], list):
                return result
            text = json.dumps(result, indent=2)
        elif isinstance(result, list):
            text = json.dumps(result, indent=2)
        else:
            text = str(result)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    async def _rpc_tools_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": list(self.tools.values())}

    async def _rpc_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_result = await self.call_tool(params.get("name", ""), params.get("arguments", {}))
        if "error" in tool_result:
            error = tool_result["error"]
            raise RpcError(error["code"], error["message"])
        return {
            "content": tool_result.get("content", []),
            "isError": tool_result.get("isError", False),
        }
