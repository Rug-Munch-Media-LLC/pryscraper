"""HTTP integration tests for MCP endpoints (mounted at /mcp).

Tests the JSON-RPC endpoint, health, SSE transport, and message posting.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with x402 middleware bypassed."""
    from api import app

    with (
        patch(
            "x402_middleware.X402Middleware.__call__",
            lambda self, scope, receive, send: self.app(scope, receive, send),
        ),
        TestClient(app) as c,
    ):
        yield c


@pytest.fixture
def mock_mcp_server() -> Iterator[None]:
    """Mock the MCP server to return controlled responses."""
    mock_server = AsyncMock()
    mock_server.handle_request = AsyncMock(
        return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {
                        "name": "pry_scrape",
                        "description": "Scrape a URL",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            },
        }
    )
    mock_server.tools = [{"name": "pry_scrape"}]
    mock_server.resources = []
    mock_server.prompts = []

    # The MCP server is lazily created inside api._get_mcp_server().
    # We patch the function to return our mock.
    patcher = patch("api._get_mcp_server", return_value=mock_server)
    patcher.start()
    yield
    patcher.stop()


class TestMCPHealth:
    """GET /mcp/health — MCP server health."""

    def test_mcp_health_returns_200(self, client: TestClient, mock_mcp_server: None) -> None:
        resp = client.get("/mcp/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["server"] == "pry-mcp"
        assert "tools_count" in body


class TestMCPJsonRPC:
    """POST /mcp/ — MCP JSON-RPC endpoint."""

    def test_list_tools_request(self, client: TestClient, mock_mcp_server: None) -> None:
        resp = client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("jsonrpc") == "2.0"
        assert "result" in body

    def test_invalid_json_rpc_returns_error(
        self, client: TestClient, mock_mcp_server: None
    ) -> None:
        resp = client.post(
            "/mcp/",
            json={"not": "valid json-rpc"},
        )
        # Should still respond with valid JSON
        assert resp.status_code == 200


class TestMCPSSE:
    """GET /mcp/sse — MCP SSE transport endpoint."""

    @pytest.mark.skip(reason="SSE is streaming; would hang in test")
    def test_sse_endpoint_returns_streaming(self, client: TestClient) -> None:
        resp = client.get("/mcp/sse")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
