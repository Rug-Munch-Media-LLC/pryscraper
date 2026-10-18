# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fallback MCP server after the module split.

Pins the two things a refactor can silently break: the JSON-RPC wire
behaviour (codes, envelopes, negotiation) and the import/patch seams the
rest of the suite relies on. Also guards the split itself — no module is
allowed to creep back over the 200-line gate budget.
"""

from __future__ import annotations

import pathlib
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

import pry_mcp.fallback_server as facade
from pry_mcp.fallback_protocol import METHOD_TABLE
from pry_mcp.fallback_server import make_fallback_server

if TYPE_CHECKING:
    from collections.abc import Iterator


def _server() -> Any:
    return make_fallback_server(base_url="http://mcp-split.invalid")


async def _call(server: Any, method: str, params: Any = None) -> dict[str, Any]:
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": 7, "method": method}
    if params is not None:
        request["params"] = params
    return await server.handle_request(request)


@contextmanager
def _patched_client(client: Any) -> Iterator[None]:
    with patch("pry_mcp.fallback_server.get_client", new=AsyncMock(return_value=client)):
        yield


def test_facade_keeps_public_imports() -> None:
    for name in (
        "FallbackMCPServer",
        "ToolRegistry",
        "_ToolNotHandled",
        "_hot_tool_cache",
        "combined_tool_executor",
        "get_client",
        "httpx",
        "make_fallback_server",
    ):
        assert hasattr(facade, name), f"facade lost {name}"
    assert facade.httpx.__name__ == "httpx"


def test_dispatch_table_covers_every_handler() -> None:
    server = _server()
    assert len(METHOD_TABLE) == 13
    for handler_name in METHOD_TABLE.values():
        assert callable(getattr(server, handler_name)), handler_name


def test_every_fallback_module_stays_within_the_gate_budget() -> None:
    root = pathlib.Path(__file__).resolve().parents[1] / "pry_mcp"
    for path in sorted(root.glob("fallback_*.py")):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 200, f"{path.name}: {lines} lines"


class TestProtocol:
    @pytest.mark.asyncio
    async def test_discover_matches_the_constant(self) -> None:
        """The fallback answers ``server/discover`` with the shared payload."""
        from pry_mcp.constants import MCP_DISCOVER_METHOD, discover_result

        server = _server()
        response = await _call(server, MCP_DISCOVER_METHOD)
        assert response["result"] == discover_result()

    @pytest.mark.asyncio
    async def test_discover_rejects_an_unsupported_modern_version(self) -> None:
        from pry_mcp.constants import (
            MCP_DISCOVER_METHOD,
            MCP_PROTOCOL_VERSION,
            MCP_PROTOCOL_VERSION_META_KEY,
            MCP_UNSUPPORTED_VERSION_CODE,
        )

        server = _server()
        response = await _call(
            server,
            MCP_DISCOVER_METHOD,
            {"_meta": {MCP_PROTOCOL_VERSION_META_KEY: "2099-01-01"}},
        )
        error = response["error"]
        assert error["code"] == MCP_UNSUPPORTED_VERSION_CODE
        assert error["data"]["requested"] == "2099-01-01"
        assert MCP_PROTOCOL_VERSION in error["data"]["supported"]

    @pytest.mark.asyncio
    async def test_initialize_echoes_supported_revision(self) -> None:
        server = _server()
        response = await _call(
            server, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {}}
        )
        result = response["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert result["capabilities"]["tools"] == {"listChanged": True}

    @pytest.mark.asyncio
    async def test_initialize_unknown_revision_falls_back_to_ceiling(self) -> None:
        from pry_mcp.constants import MCP_PROTOCOL_VERSION

        server = _server()
        response = await _call(server, "initialize", {"protocolVersion": "2099-01-01"})
        assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_ping_and_logging_set_level(self) -> None:
        server = _server()
        assert await _call(server, "ping") == {"jsonrpc": "2.0", "id": 7, "result": {}}
        assert (await _call(server, "logging/setLevel", {"level": "debug"}))["result"] == {}

    @pytest.mark.asyncio
    async def test_notification_never_responds_but_marks_initialized(self) -> None:
        server = _server()
        assert (
            await server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
            is None
        )
        assert server._initialized is True

    @pytest.mark.asyncio
    async def test_error_codes(self) -> None:
        server = _server()
        assert (await server.handle_request("nope"))["error"]["code"] == -32600
        assert (await _call(server, ""))["error"]["code"] == -32600
        assert (await _call(server, "does/not/exist"))["error"]["code"] == -32601
        # params=None reaches the handler and fails inside it -> -32603
        broken = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": None}
        assert (await server.handle_request(broken))["error"]["code"] == -32603


class TestTools:
    @pytest.mark.asyncio
    async def test_unknown_tool_is_minus_32602(self) -> None:
        response = await _call(_server(), "tools/call", {"name": "nope", "arguments": {}})
        assert response["error"] == {"code": -32602, "message": "Unknown tool: nope"}

    @pytest.mark.asyncio
    async def test_tools_list_and_call_shape(self) -> None:
        server = _server()
        server.register_tool("pry_scrape", {"name": "pry_scrape"})
        listed = await _call(server, "tools/list")
        assert listed["result"]["tools"] == [{"name": "pry_scrape"}]

        async def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        server.tool_executor = executor
        called = await _call(server, "tools/call", {"name": "pry_scrape", "arguments": {}})
        assert called["result"]["isError"] is False
        assert '"ok": true' in called["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_rest_proxy_uses_the_facade_get_client_seam(self) -> None:
        server = _server()
        server.register_tool("pry_scrape", {"name": "pry_scrape"})
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {"success": True}
        client = AsyncMock()
        client.request.return_value = response
        with _patched_client(client):
            args = {"url": "https://example.com"}
            result = await _call(server, "tools/call", {"name": "pry_scrape", "arguments": args})
        assert client.request.call_args[0][0] == "POST"
        assert result["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_unwired_tool_reports_tool_not_wired(self) -> None:
        server = _server()
        server.register_tool("pry_unwired", {"name": "pry_unwired"})
        result = await server.call_tool("pry_unwired", {})
        assert result["isError"] is True
        assert "TOOL_NOT_WIRED" in result["content"][0]["text"]


class TestResourcesPrompts:
    @pytest.mark.asyncio
    async def test_resource_and_prompt_lists_start_empty(self) -> None:
        server = _server()
        assert (await _call(server, "resources/list"))["result"]["resources"] == []
        assert (await _call(server, "prompts/list"))["result"]["prompts"] == []

    @pytest.mark.asyncio
    async def test_missing_resource_is_an_error_envelope(self) -> None:
        response = await _call(_server(), "resources/read", {"uri": "pry://missing"})
        assert response["error"]["code"] == -32602
        assert "Resource not found" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_subscription_lifecycle(self) -> None:
        server = _server()
        server.register_resource("pry://feed", {"uri": "pry://feed"})
        subscribed = await _call(server, "resources/subscribe", {"uri": "pry://feed"})
        assert subscribed["result"] == {"subscribed": True}
        dropped = await _call(server, "resources/unsubscribe", {"uri": "pry://feed"})
        assert dropped["result"] == {"unsubscribed": True}
        missing = await _call(server, "resources/subscribe", {"uri": "pry://nope"})
        assert missing["result"] == {"subscribed": False}

    @pytest.mark.asyncio
    async def test_completion_returns_values(self) -> None:
        response = await _call(_server(), "completion/complete", {"ref": {}, "argument": {}})
        assert response["result"] == {"values": []}
