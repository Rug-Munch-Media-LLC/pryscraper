# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 2: round-trip tools/call for every tool."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from pry_mcp.tools import call_actor_tool

from ._support import _call, _fake_module, _patch_module, _server
from ._tables import _DOMAIN_TOOLS, _LOCAL_ACTOR_TOOLS, _REST_PROXY_TOOLS


class TestToolRoundTrips:
    """Every tool must answer tools/call with a JSON-RPC success or a readable
    not-available message — never an internal error."""

    @pytest.mark.parametrize("tool_name", sorted(_DOMAIN_TOOLS))
    async def test_domain_tool_success(self, tool_name: str) -> None:
        module_name, fns, args = _DOMAIN_TOOLS[tool_name]
        fake = _fake_module(
            **{fn: AsyncMock(return_value={"ok": True, "tool": tool_name}) for fn in fns}
        )
        srv = _server()
        with _patch_module(module_name, fake):
            resp = await _call(srv, tool_name, args)
        assert resp["jsonrpc"] == "2.0"
        assert "error" not in resp, f"{tool_name}: {resp.get('error')}"
        result = resp["result"]
        assert isinstance(result["content"], list), f"{tool_name}: content not a list"
        assert result["content"], f"{tool_name}: empty content"
        assert result["isError"] is False
        # The mocked payload may be nested under "data" by the domain
        # dispatcher wrappers (legal/jobs/travel/etc.), or at the top level
        # (crypto/marketplace serialize the raw data) — accept both.
        text = result["content"][0]["text"]
        payload = json.loads(text)
        assert payload.get("ok") is True or payload.get("data", {}).get("ok") is True, (
            f"{tool_name}: mocked payload missing: {text[:200]}"
        )

    @pytest.mark.parametrize("tool_name", sorted(_REST_PROXY_TOOLS))
    async def test_rest_proxy_tool_success(self, tool_name: str) -> None:
        srv = _server()
        args = _REST_PROXY_TOOLS[tool_name]
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True, "data": {"tool": tool_name}}
        mock_client.get.return_value = mock_response
        mock_client.post.return_value = mock_response
        with patch("pry_mcp.fallback_server.httpx.AsyncClient", return_value=mock_client):
            resp = await _call(srv, tool_name, args)
        assert resp["jsonrpc"] == "2.0"
        assert "error" not in resp, f"{tool_name}: {resp.get('error')}"
        assert resp["result"]["content"], f"{tool_name}: empty content"
        assert resp["result"]["isError"] is False

    @pytest.mark.parametrize("tool_name", sorted(_LOCAL_ACTOR_TOOLS))
    async def test_local_actor_tool_success(self, tool_name: str) -> None:
        """Actor-parity tools execute locally through call_actor_tool with a
        mocked UltimateScraper - no network, no REST proxy."""
        import actor_factory.runner as runner_mod

        class FakeScraper:
            async def scrape(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
                return {
                    "status": "ok",
                    "method": "direct",
                    "content": f"content for {url}",
                    "raw_html": "<html>hi</html>",
                    "scraped_at": "2026-08-26T00:00:00+00:00",
                }

        real_init = runner_mod.PPEScraperRunner.__init__

        def patched(self: Any, config: Any, actor_module: Any = None) -> None:
            real_init(self, config, actor_module)
            self._scraper = FakeScraper()

        with patch.object(runner_mod.PPEScraperRunner, "__init__", patched):
            result = await call_actor_tool(tool_name, _LOCAL_ACTOR_TOOLS[tool_name])
        assert result is not None, f"{tool_name}: not handled by call_actor_tool"
        assert result.get("isError") is not True, f"{tool_name}: {result}"
        payload = json.loads(result["content"][0]["text"])
        if tool_name == "pry_actor_catalog":
            assert payload["total"] > 0
            assert any(a["actor"] == "change-monitor" for a in payload["actors"])
        else:
            assert payload["item_count"] == 1
            assert payload["actor"] == "universal-scraper"

    @pytest.mark.parametrize("tool_name", sorted(_DOMAIN_TOOLS))
    async def test_domain_tool_missing_module_is_readable(self, tool_name: str) -> None:
        """Module absent -> readable 'not available' message, not a crash."""
        module_name, _fns, args = _DOMAIN_TOOLS[tool_name]
        srv = _server()
        with _patch_module(module_name, None):
            resp = await _call(srv, tool_name, args)
        assert resp["jsonrpc"] == "2.0"
        assert "error" not in resp, f"{tool_name}: {resp.get('error')}"
        result = resp["result"]
        assert result["isError"] is False
        assert "not available" in result["content"][0]["text"]

    async def test_rest_proxy_unreachable_is_readable(self) -> None:
        """API down -> readable 'Would call ...' message for REST tools."""
        srv = _server()
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("connection refused")
        # The proxy awaits get_client() and calls .request() — patch there.
        with patch(
            "pry_mcp.fallback_server.get_client",
            new=AsyncMock(return_value=mock_client),
        ):
            resp = await _call(srv, "pry_scrape", {"url": "https://example.com"})
        assert "error" not in resp
        # API down is a structured tool error (isError=True), not a fake success.
        assert resp["result"]["isError"] is True
        assert "Would call POST /v1/scrape" in resp["result"]["content"][0]["text"]

    async def test_pry_compliance_url_falls_through_to_rest_proxy(self) -> None:
        """pry_compliance with only a URL keeps the legacy REST-proxy mode.

        The compliance dispatcher declines url-only calls (no query/agency) so
        the original POST /v1/compliance/check path stays wired — the mocked
        httpx client must receive the REST call, not a 'not available' message.
        """
        srv = _server()
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True, "data": {"risk_level": "green"}}
        mock_client.request.return_value = mock_response
        with patch(
            "pry_mcp.fallback_server.get_client",
            new=AsyncMock(return_value=mock_client),
        ):
            resp = await _call(srv, "pry_compliance", {"url": "https://example.com"})
        assert resp["jsonrpc"] == "2.0"
        assert "error" not in resp, f"pry_compliance url fall-through failed: {resp.get('error')}"
        assert resp["result"]["content"], "pry_compliance url fall-through: empty content"
        assert resp["result"]["isError"] is False
        # The REST proxy path was taken (POST /v1/compliance/check).
        assert mock_client.request.called is True
        assert mock_client.request.call_args[0][0] == "POST"
        assert "/v1/compliance/check" in mock_client.request.call_args[0][1]

    async def test_unknown_tool_returns_jsonrpc_error(self) -> None:
        srv = _server()
        resp = await _call(srv, "pry_not_a_real_tool", {})
        assert "error" in resp
        assert resp["error"]["code"] == -32602
