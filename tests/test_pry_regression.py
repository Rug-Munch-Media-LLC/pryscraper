# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""
Regression tests for live Pry bugs just fixed.

These tests pin the exact behaviors that were broken and are now fixed:
1. DEFAULT_BASE_URL prefers PRY_URL over PRY_API_URL over localhost:8002
2. REST proxy success includes structuredContent when tool advertises outputSchema
3. API failure returns API_UNAVAILABLE with "Would call ..." envelope, not a crash
4. Owner key (PRY_API_KEY) bypasses x402 gate; missing/invalid key gets 402
5. pry_scrape returns success/data/markdown shape via mocked HTTP (no live network)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from pry_mcp.fallback_server import make_fallback_server
from pry_mcp.tool_registry import combined_tool_executor
from pry_mcp.tools import PRY_TOOLS


class TestDefaultBaseUrlPrecedence:
    """DEFAULT_BASE_URL must prefer PRY_URL over PRY_API_URL over localhost:8002."""

    def test_pry_url_wins_over_pry_api_url(self, monkeypatch: MonkeyPatch) -> None:
        """PRY_URL takes precedence when both are set."""
        monkeypatch.setenv("PRY_URL", "http://pry-url.example.com")
        monkeypatch.setenv("PRY_API_URL", "http://pry-api-url.example.com")
        import importlib

        import pry_mcp.constants as constants
        importlib.reload(constants)
        assert constants.DEFAULT_BASE_URL == "http://pry-url.example.com"

    def test_pry_api_url_used_when_pry_url_absent(self, monkeypatch: MonkeyPatch) -> None:
        """PRY_API_URL is used when PRY_URL is not set."""
        monkeypatch.delenv("PRY_URL", raising=False)
        monkeypatch.setenv("PRY_API_URL", "http://pry-api-url.example.com")
        import importlib

        import pry_mcp.constants as constants
        importlib.reload(constants)
        assert constants.DEFAULT_BASE_URL == "http://pry-api-url.example.com"

    def test_localhost_fallback_when_neither_set(self, monkeypatch: MonkeyPatch) -> None:
        """Defaults to localhost:8002 when neither env var is set."""
        monkeypatch.delenv("PRY_URL", raising=False)
        monkeypatch.delenv("PRY_API_URL", raising=False)
        import importlib

        import pry_mcp.constants as constants
        importlib.reload(constants)
        assert constants.DEFAULT_BASE_URL == "http://localhost:8002"

    def test_pry_url_overrides_localhost(self, monkeypatch: MonkeyPatch) -> None:
        """Explicit PRY_URL overrides the localhost default."""
        monkeypatch.setenv("PRY_URL", "http://custom.example.com")
        monkeypatch.delenv("PRY_API_URL", raising=False)
        import importlib

        import pry_mcp.constants as constants
        importlib.reload(constants)
        assert constants.DEFAULT_BASE_URL == "http://custom.example.com"


class TestStructuredContentOnSuccess:
    """REST proxy success must include structuredContent when tool advertises outputSchema."""

    @pytest.fixture
    def server(self) -> Any:
        server = make_fallback_server(tool_executor=combined_tool_executor)
        scrape_tool = next(t for t in PRY_TOOLS if t["name"] == "pry_scrape")
        server.register_tool("pry_scrape", scrape_tool)
        return server

    async def _call_rpc(self, server: Any, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            request["params"] = params
        return await server.handle_request(request)

    async def test_rest_proxy_success_includes_structured_content(self, server: Any) -> None:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "url": "https://example.com",
                "title": "Test Page",
                "content": "# Test Page\n\nContent here",
                "links": [],
                "images": [],
                "status_code": 200,
            },
        }
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com"}})

        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is False
        assert "structuredContent" in tool_result
        assert tool_result["structuredContent"]["success"] is True
        assert tool_result["structuredContent"]["data"]["title"] == "Test Page"
        assert tool_result["structuredContent"]["data"]["url"] == "https://example.com"

    async def test_tool_without_output_schema_no_structured_content(self, server: Any) -> None:
        server.register_tool("no_schema_tool", {"name": "no_schema_tool"})
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True, "data": "raw"}
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        async def _fake_call(name: str, arguments: dict) -> dict:
            return {
                "content": [{"type": "text", "text": '{"success": true, "data": "raw"}'}],
                "isError": False,
            }

        with patch.object(server, "call_tool", side_effect=_fake_call):
            result = await self._call_rpc(server, "tools/call", {"name": "no_schema_tool", "arguments": {}})

        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is False
        assert "structuredContent" not in tool_result


class TestApiFailureReturnsApiUnavailable:
    """API failure must return API_UNAVAILABLE with 'Would call ...' envelope, not crash."""

    @pytest.fixture
    def server(self) -> Any:
        server = make_fallback_server(tool_executor=combined_tool_executor)
        scrape_tool = next(t for t in PRY_TOOLS if t["name"] == "pry_scrape")
        server.register_tool("pry_scrape", scrape_tool)
        return server

    async def _call_rpc(self, server: Any, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            request["params"] = params
        return await server.handle_request(request)

    async def test_connection_error_returns_api_unavailable(self, server: Any) -> None:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("connection refused")
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com"}})
        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is True
        payload = json.loads(tool_result["content"][0]["text"])
        assert payload["code"] == "API_UNAVAILABLE"
        assert "Would call POST /v1/scrape" in payload["error"]
        assert "Live execution unavailable" in payload["error"]

    async def test_timeout_returns_api_unavailable(self, server: Any) -> None:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.TimeoutException("timeout")
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com"}})
        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is True
        payload = json.loads(tool_result["content"][0]["text"])
        assert payload["code"] == "API_UNAVAILABLE"
        assert "Would call POST /v1/scrape" in payload["error"]

    async def test_http_error_returns_api_unavailable(self, server: Any) -> None:
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error", request=Mock(), response=Mock(status_code=500)
        )
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com"}})
        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is True
        payload = json.loads(tool_result["content"][0]["text"])
        assert payload["code"] == "API_UNAVAILABLE"
        assert "Would call POST /v1/scrape" in payload["error"]

    async def test_request_error_returns_api_unavailable(self, server: Any) -> None:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.RequestError("dns resolution failed")
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com"}})
        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is True
        payload = json.loads(tool_result["content"][0]["text"])
        assert payload["code"] == "API_UNAVAILABLE"


class TestOwnerKeyBypassesX402:
    """Owner key (PRY_API_KEY) bypasses x402 gate; missing/invalid key gets 402."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from pry.payments.x402 import FacilitatorRouter, X402Handler, set_facilitator_router
        from pry.payments.x402_middleware import X402Middleware

        app = FastAPI()

        @app.get("/v1/scrape")
        async def scrape():
            return {"ok": True, "data": "scraped"}

        class TestRouter(FacilitatorRouter):
            def __init__(self):
                super().__init__(facilitators=[])

            async def verify(self, **kwargs) -> dict[str, Any]:
                return {"verified": True, "reason": "", "settlement": None, "facilitator": "test"}

            async def settle(self, **kwargs) -> dict[str, Any]:
                return {"success": True, "transaction": kwargs.get("tx_hash", ""), "facilitator": "test"}

        set_facilitator_router(TestRouter())
        handler = X402Handler()
        mw = X402Middleware(app=app)
        mw.handler = handler
        return TestClient(mw, raise_server_exceptions=False)

    def test_valid_api_key_bypasses_x402(self, app, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_API_KEY", "pry_test_valid_key_12345")
        response = app.get("/v1/scrape", headers={"Authorization": "Bearer pry_test_valid_key_12345"})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "data": "scraped"}

    def test_missing_api_key_returns_402(self, app, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_API_KEY", "pry_test_valid_key_12345")
        response = app.get("/v1/scrape")
        assert response.status_code == 402
        assert "PAYMENT-REQUIRED" in response.headers

    def test_invalid_api_key_returns_402(self, app, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_API_KEY", "pry_test_valid_key_12345")
        response = app.get("/v1/scrape", headers={"Authorization": "Bearer invalid_key"})
        assert response.status_code == 402
        assert "PAYMENT-REQUIRED" in response.headers

    def test_empty_api_key_returns_402(self, app, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_API_KEY", "pry_test_valid_key_12345")
        response = app.get("/v1/scrape", headers={"Authorization": "Bearer "})
        assert response.status_code == 402

    def test_x402_payment_works_when_no_owner_key(self, app, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.delenv("PRY_API_KEY", raising=False)
        import base64
        sig = base64.b64encode(json.dumps({
            "payment_id": "test-pay-123",
            "tx_hash": "0xabc123",
            "network": "base",
            "asset": "USDC",
            "amount_usd": 0.001,
        }).encode()).decode()
        response = app.get("/v1/scrape", headers={"PAYMENT-SIGNATURE": sig})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "data": "scraped"}


class TestPryScrapeContractShape:
    """pry_scrape must return success/data/markdown shape via mocked HTTP."""

    @pytest.fixture
    def server(self) -> Any:
        server = make_fallback_server(tool_executor=combined_tool_executor)
        scrape_tool = next(t for t in PRY_TOOLS if t["name"] == "pry_scrape")
        server.register_tool("pry_scrape", scrape_tool)
        return server

    async def _call_rpc(self, server: Any, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            request["params"] = params
        return await server.handle_request(request)

    async def test_pry_scrape_returns_success_data_markdown_shape(self, server: Any) -> None:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "url": "https://example.com/article",
                "title": "Example Article",
                "content": "# Example Article\n\nThis is the **markdown content** of the article.\n\n## Section\n\nMore content here.",
                "links": ["https://example.com/link1", "https://example.com/link2"],
                "images": ["https://example.com/image1.jpg", "https://example.com/image2.png"],
                "status_code": 200,
            },
        }
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {"name": "pry_scrape", "arguments": {"url": "https://example.com/article"}})

        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is False
        assert "structuredContent" in tool_result
        sc = tool_result["structuredContent"]
        assert sc["success"] is True
        assert "data" in sc
        data = sc["data"]
        assert data["url"] == "https://example.com/article"
        assert data["title"] == "Example Article"
        assert isinstance(data["content"], str)
        assert "markdown content" in data["content"]
        assert isinstance(data["links"], list)
        assert len(data["links"]) == 2
        assert isinstance(data["images"], list)
        assert len(data["images"]) == 2
        assert data["status_code"] == 200

    async def test_pry_scrape_with_bypass_cloudflare_option(self, server: Any) -> None:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "url": "https://example.com",
                "title": "Cloudflare Protected",
                "content": "Content after bypass",
                "links": [],
                "images": [],
                "status_code": 200,
            },
        }
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {
                "name": "pry_scrape",
                "arguments": {"url": "https://cloudflare-protected.example.com", "bypass_cloudflare": True, "js_render": True}
            })

        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is False
        call_args = mock_client.request.call_args
        assert call_args is not None
        assert call_args[1]["json"]["bypass_cloudflare"] is True
        assert call_args[1]["json"]["js_render"] is True

    async def test_pry_scrape_with_extract_schema(self, server: Any) -> None:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "url": "https://example.com/products",
                "title": "Products",
                "content": "Product listing page",
                "links": [],
                "images": [],
                "status_code": 200,
            },
        }
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response

        extract_schema = {
            "name": "product",
            "base_selector": ".product-card",
            "fields": [
                {"name": "name", "selector": ".product-title", "type": "text"},
                {"name": "price", "selector": ".price", "type": "text"},
            ],
        }

        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await self._call_rpc(server, "tools/call", {
                "name": "pry_scrape",
                "arguments": {"url": "https://example.com/products", "extract_schema": extract_schema}
            })

        assert "result" in result
        tool_result = result["result"]
        assert tool_result["isError"] is False
        call_args = mock_client.request.call_args
        assert call_args[1]["json"]["extract_schema"] == extract_schema


class TestCombinedCoverage:
    def test_constants_module_coverage(self) -> None:
        from pry_mcp import constants
        assert constants.DEFAULT_BASE_URL is not None
        assert constants.MCP_PROTOCOL_VERSION == "2026-07-28"
        assert constants.SERVER_NAME == "pry"

    def test_fallback_tools_module_coverage(self) -> None:
        from pry_mcp import fallback_tools
        assert fallback_tools.TOOL_ROUTES is not None
        assert "pry_scrape" in fallback_tools.TOOL_ROUTES

    def test_fallback_factory_module_coverage(self) -> None:
        from pry_mcp import fallback_factory
        server = fallback_factory.make_fallback_server()
        assert server is not None

    def test_tool_routes_module_coverage(self) -> None:
        from pry_mcp import tool_routes
        assert tool_routes.TOOL_ROUTES is not None
        assert len(tool_routes.TOOL_ROUTES) >= 49
