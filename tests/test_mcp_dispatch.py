# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP call-path tests: tool dispatch through the production fallback server.

The schema-integrity suite (test_mcp_tool_surface.py) validates the static
surface; this module exercises the DYNAMIC path - register -> list ->
call_tool -> executor result wrapping - plus error handling for unknown
tools and malformed arguments.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pry_mcp.fallback_server import make_fallback_server
from pry_mcp.tools import PRY_TOOLS


def _server_with_executor(
    handler: Any = None,
) -> Any:
    """Build a fallback server whose executor returns canned payloads."""

    async def default_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if handler:
            return await handler(name, args)
        return {"ok": True, "tool": name, "args": args}

    return make_fallback_server(tool_executor=default_executor)


def _register_all(server: Any) -> None:
    for entry in PRY_TOOLS:
        server.register_tool(entry["name"], entry)


class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_known_tool_dispatches_to_executor(self) -> None:
        seen: dict[str, Any] = {}

        async def handler(name: str, args: dict[str, Any]) -> dict[str, Any]:
            seen["name"] = name
            seen["args"] = args
            return {"result": "payload"}

        server = _server_with_executor(handler)
        _register_all(server)
        target = PRY_TOOLS[0]["name"]
        result = await server.call_tool(target, {"url": "https://example.com"})
        assert seen["name"] == target
        assert seen["args"] == {"url": "https://example.com"}
        assert result  # non-empty content list

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_jsonrpc_error(self) -> None:
        """MCP-compliant: unknown tools yield error code -32602, no raise."""
        server = _server_with_executor()
        _register_all(server)
        result = await server.call_tool("totally_not_a_tool", {})
        assert result["error"]["code"] == -32602
        assert "Unknown tool" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_empty_arguments_defaulted(self) -> None:
        """call_tool with None arguments must not crash the executor."""
        server = _server_with_executor()
        _register_all(server)
        target = PRY_TOOLS[0]["name"]
        result = await server.call_tool(target, None)  # type: ignore[arg-type]
        assert result


class TestRegistrationSurface:
    def test_register_tool_idempotent_by_name(self) -> None:
        server = _server_with_executor()
        entry = PRY_TOOLS[0]
        server.register_tool(entry["name"], entry)
        server.register_tool(entry["name"], entry)
        tools = server.list_tools()["tools"]
        assert len([t for t in tools if t["name"] == entry["name"]]) == 1

    def test_resources_and_prompts_registrable(self) -> None:
        server = _server_with_executor()
        server.register_resource("pry://docs", {"content": "hello"})
        server.register_prompt("greet", {"template": "hi"})
        assert server.resources["pry://docs"]["content"] == "hello"
        assert server.prompts["greet"]["template"] == "hi"

    def test_resource_subscription_lifecycle(self) -> None:
        server = _server_with_executor()
        server.register_resource("pry://feed", {"items": []})
        assert server.subscribe_resource("pry://feed", "client-1") is True
        assert server.unsubscribe_resource("pry://feed", "client-1") is True
        assert server.unsubscribe_resource("pry://feed", "client-1") is False
        assert server.subscribe_resource("pry://missing", "c") is False


class TestJsonRpcShape:
    """The fallback server speaks MCP 2024-11-05 JSON-RPC; verify the
    content wrapper shape returned by call_tool."""

    @pytest.mark.asyncio
    async def test_result_items_are_text_content(self) -> None:
        """Executor dicts are normalized into MCP content arrays with
        JSON-serialized text payloads."""
        server = _server_with_executor()
        _register_all(server)
        target = PRY_TOOLS[0]["name"]
        result = await server.call_tool(target, {})
        # dict results come back as {"content": [{"type": "text", ...}]}
        assert isinstance(result, dict)
        items = result["content"]
        for item in items:
            assert item["type"] == "text"
            json.loads(item["text"])  # payload is valid JSON text
        assert result.get("isError") is not True
