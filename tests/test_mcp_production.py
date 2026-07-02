# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for production MCP server."""

import asyncio

from mcp_production import MCP_PROTOCOL_VERSION, PRY_TOOLS, make_fallback_server, register_all


def test_mcp_protocol_version() -> None:
    assert MCP_PROTOCOL_VERSION is not None
    assert isinstance(MCP_PROTOCOL_VERSION, str)
    assert MCP_PROTOCOL_VERSION == "2024-11-05"


def test_server_creation() -> None:
    server = make_fallback_server()
    register_all(server)
    assert server is not None
    assert len(server.tools) >= 10
    assert len(server.resources) >= 3


def test_required_tools() -> None:
    server = make_fallback_server()
    register_all(server)
    required = [
        "pry_scrape",
        "pry_crawl",
        "pry_extract",
        "pry_template",
        "pry_monitor",
        "pry_compliance",
        "pry_enrich",
        "pry_screenshot",
    ]
    for tool_name in required:
        assert tool_name in server.tools, f"Missing tool: {tool_name}"


def test_tool_schemas() -> None:
    for tool in PRY_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema.get("type") == "object"
        assert "properties" in schema
        assert "required" in schema


def test_scrape_tool_schema() -> None:
    scrape = next(t for t in PRY_TOOLS if t["name"] == "pry_scrape")
    assert "url" in scrape["inputSchema"]["required"]
    assert "url" in scrape["inputSchema"]["properties"]


def test_resources() -> None:
    server = make_fallback_server()
    register_all(server)
    assert "pry://catalog" in server.resources
    assert "pry://stats" in server.resources
    assert "pry://x402/pricing" in server.resources
    assert "pry://referrals" in server.resources


def test_fallback_initialize() -> None:
    server = make_fallback_server()
    register_all(server)
    result = asyncio.run(
        server.handle_request({"method": "initialize", "id": 1, "params": {}})
    )
    assert "protocolVersion" in result["result"]
    assert result["result"]["serverInfo"]["name"] == "pry"
    assert result["result"]["serverInfo"]["version"] == "3.0.0"


def test_fallback_tools_list() -> None:
    server = make_fallback_server()
    register_all(server)
    result = asyncio.run(server.handle_request({"method": "tools/list", "id": 1}))
    assert "tools" in result["result"]
    assert len(result["result"]["tools"]) >= 10


def test_fallback_ping() -> None:
    server = make_fallback_server()
    result = asyncio.run(server.handle_request({"method": "ping", "id": 1}))
    assert result["result"] == {}


def test_fallback_unknown_method() -> None:
    server = make_fallback_server()
    result = asyncio.run(server.handle_request({"method": "unknown", "id": 1}))
    assert "error" in result
    assert result["error"]["code"] == -32601
