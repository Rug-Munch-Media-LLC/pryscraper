# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the MCP tool dispatch path (pry_mcp.tools + fallback server).

Covers the guarded local dispatchers used by the MCP servers:

* ``call_crypto_tool`` / ``call_marketplace_tool`` — the original two
  domain dispatchers;
* ``call_legal_tool`` — one of the data-domain dispatchers added by the
  parallel domain build (the dispatch *layer* is tested here; the domain
  packages' own behavior is covered by their own test files);
* ``combined_tool_executor`` — the chained executor that falls through
  from crypto -> marketplace -> data domains -> ``_ToolNotHandled``;
* the fallback server's REST-proxy fallback for generic tools.

Two behaviors are asserted for every dispatcher:

* a **missing** module returns a readable "not available" MCP text
  message (``isError=False``) instead of crashing with ImportError;
* a **present** module returns its data serialized into the MCP content
  array (mocked via ``sys.modules`` so no network / no real domain code
  is exercised and the tests are hermetic).
"""

from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

import pry_mcp.tools as mcp_tools
from pry_mcp.fallback_server import (
    _ToolNotHandled,
    combined_tool_executor,
    make_fallback_server,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _patch_module(name: str, module: Any) -> Iterator[None]:
    """Swap ``sys.modules[name]`` for the duration of the test.

    ``module`` may be ``None`` (simulates a module that has not landed yet:
    CPython raises ``ImportError`` for ``from X import Y`` when
    ``sys.modules[X]`` is None, which is exactly what the guarded dispatchers
    catch) or a fake module object (present-module path).

    The parent package is imported *first*: packages like ``crypto_market``
    eagerly import every submodule in ``__init__``, so patching a submodule
    before the parent exists would make the parent's own import fail and
    leave ``sys.modules`` in a wedged state for later tests.
    """
    if "." in name:
        # Parent genuinely unavailable -> the dispatcher handles it.
        with suppress(ImportError):
            __import__(name.rsplit(".", 1)[0])
    original: Any = sys.modules.get(name, _MISSING)
    sys.modules[name] = module
    try:
        yield
    finally:
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


_MISSING = object()


def _fake_module(**attrs: Any) -> types.ModuleType:
    """Build a minimal module object exposing async callables (AsyncMock)."""
    module = types.ModuleType("fake")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _text(result: dict[str, Any]) -> str:
    """Extract the MCP text payload from a dispatcher result."""
    return result["content"][0]["text"]


class TestCallCryptoTool:
    async def test_missing_module_returns_not_available(self) -> None:
        """A crypto module that has not landed must not crash the dispatch."""
        with _patch_module("datasets.crypto_market.token_launches", None):
            result = await mcp_tools.call_crypto_tool("pry_token_launches", {})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        text = _text(result)
        assert "not available" in text
        assert "pry_token_launches" in text

    async def test_cex_listings_missing_returns_not_available(self) -> None:
        with _patch_module("datasets.crypto_market.cex_listings", None):
            result = await mcp_tools.call_crypto_tool(
                "pry_cex_listings", {"exchanges": ["binance"], "lookback_hours": 24}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert "not available" in _text(result)

    async def test_token_security_missing_returns_not_available(self) -> None:
        with _patch_module("crypto_market.token_security", None):
            result = await mcp_tools.call_crypto_tool(
                "pry_token_security",
                {"chain": "solana", "address": "So11111111111111111111111111111111111111112"},
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert "not available" in _text(result)

    async def test_token_security_missing_arguments_is_error(self) -> None:
        result = await mcp_tools.call_crypto_tool("pry_token_security", {"chain": "solana"})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is True
        assert "requires" in _text(result)

    async def test_present_module_returns_data(self) -> None:
        """A landed module returns its data serialized into the content array."""
        fake = _fake_module(
            get_new_tokens=AsyncMock(return_value={"items": [{"symbol": "TEST"}]}),
            get_new_pairs=AsyncMock(return_value={"items": []}),
            get_trending_tokens=AsyncMock(return_value={"items": []}),
        )
        with _patch_module("datasets.crypto_market.token_launches", fake):
            result = await mcp_tools.call_crypto_tool(
                "pry_token_launches", {"chain": "solana", "limit": 5}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        payload = json.loads(_text(result))
        assert payload["data"]["items"][0]["symbol"] == "TEST"
        fake.get_new_tokens.assert_awaited_once_with(chain="solana", limit=5)

    async def test_non_crypto_tool_returns_none(self) -> None:
        """Foreign tools fall through so the caller can try the next executor."""
        assert (
            await mcp_tools.call_crypto_tool("pry_scrape", {"url": "https://example.com"}) is None
        )


class TestCallMarketplaceTool:
    async def test_missing_module_returns_not_available(self) -> None:
        with _patch_module("pry.commerce.marketplace.amazon", None):
            result = await mcp_tools.call_marketplace_tool(
                "pry_amazon_product", {"asin": "B08N5WRWNW"}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        text = _text(result)
        assert "not available" in text
        assert "pry_amazon_product" in text

    async def test_tiktok_missing_returns_not_available(self) -> None:
        with _patch_module("pry.commerce.marketplace.tiktok_shop", None):
            result = await mcp_tools.call_marketplace_tool("pry_tiktok_trending", {"limit": 5})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert "not available" in _text(result)

    async def test_missing_required_argument_is_error(self) -> None:
        result = await mcp_tools.call_marketplace_tool("pry_amazon_product", {})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is True
        assert "requires" in _text(result)

    async def test_present_module_returns_data(self) -> None:
        fake = _fake_module(
            get_product=AsyncMock(return_value={"asin": "B08N5WRWNW", "price": 9.99})
        )
        with _patch_module("pry.commerce.marketplace.amazon", fake):
            result = await mcp_tools.call_marketplace_tool(
                "pry_amazon_product", {"asin": "B08N5WRWNW"}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        payload = json.loads(_text(result))
        assert payload["data"]["asin"] == "B08N5WRWNW"
        fake.get_product.assert_awaited_once_with("B08N5WRWNW")

    async def test_non_marketplace_tool_returns_none(self) -> None:
        assert await mcp_tools.call_marketplace_tool("pry_scrape", {}) is None


class TestCallLegalTool:
    """One data-domain dispatcher (legal) — the dispatch layer, not the package."""

    async def test_missing_module_returns_not_available(self) -> None:
        with _patch_module("datasets.legal_docs.dockets", None):
            result = await mcp_tools.call_legal_tool(
                "pry_legal_dockets", {"query": "OpenAI copyright"}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        text = _text(result)
        assert "not available" in text
        assert "legal_docs" in text

    async def test_missing_required_argument_is_error(self) -> None:
        result = await mcp_tools.call_legal_tool("pry_legal_dockets", {})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is True
        assert "requires query" in _text(result)

    async def test_present_module_returns_data(self) -> None:
        fake = _fake_module(
            search_dockets=AsyncMock(
                return_value=[{"id": 1, "case_name": "ACME v. Corp", "court": "SDNY"}]
            )
        )
        with _patch_module("datasets.legal_docs.dockets", fake):
            result = await mcp_tools.call_legal_tool(
                "pry_legal_dockets", {"query": "OpenAI", "limit": 2}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        payload = json.loads(_text(result))
        assert payload["success"] is True
        assert payload["data"][0]["case_name"] == "ACME v. Corp"
        fake.search_dockets.assert_awaited_once_with(query="OpenAI", limit=2)

    async def test_non_legal_tool_returns_none(self) -> None:
        assert await mcp_tools.call_legal_tool("pry_scrape", {}) is None


class TestCombinedToolExecutor:
    """The chained executor must route each tool to the right dispatcher."""

    async def test_crypto_tool_routed_first(self) -> None:
        fake = _fake_module(
            get_new_tokens=AsyncMock(return_value={"items": []}),
            get_new_pairs=AsyncMock(return_value={"items": []}),
            get_trending_tokens=AsyncMock(return_value={"items": []}),
        )
        with _patch_module("datasets.crypto_market.token_launches", fake):
            result = await combined_tool_executor("pry_token_launches", {"chain": "all"})
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert "items" in _text(result)

    async def test_domain_tool_falls_through_to_domain_dispatcher(self) -> None:
        """Crypto/marketplace decline the tool; the legal dispatcher serves it."""
        fake = _fake_module(search_dockets=AsyncMock(return_value=[]))
        with _patch_module("datasets.legal_docs.dockets", fake):
            result = await combined_tool_executor(
                "pry_legal_dockets", {"query": "OpenAI", "limit": 1}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert json.loads(_text(result))["success"] is True

    async def test_unknown_tool_raises_tool_not_handled(self) -> None:
        """Nothing owns the tool -> _ToolNotHandled so the REST proxy can try."""
        with pytest.raises(_ToolNotHandled):
            await combined_tool_executor("pry_scrape", {"url": "https://example.com"})

    async def test_missing_domain_module_returns_not_available(self) -> None:
        with _patch_module("datasets.legal_docs.sec_filings", None):
            result = await combined_tool_executor(
                "pry_legal_sec", {"ticker": "AAPL", "form_type": "8-K"}
            )
        assert result is not None
        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["isError"] is False
        assert "not available" in _text(result)


class TestFallbackServerRESTProxy:
    """Generic tools that no domain owns fall through to the REST proxy."""

    def _server(self) -> Any:
        server = make_fallback_server(tool_executor=combined_tool_executor)
        server.register_tool("pry_scrape", {"name": "pry_scrape"})
        server.register_tool("pry_unknown", {"name": "pry_unknown"})
        return server

    async def test_rest_proxy_success_returns_data(self) -> None:
        server = self._server()
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"success": True, "data": {"url": "https://example.com"}}
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await server.call_tool("pry_scrape", {"url": "https://example.com"})
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert payload["success"] is True
        mock_client.request.assert_awaited_once()

    async def test_rest_proxy_unreachable_returns_readable_message(self) -> None:
        """API down -> readable 'Would call ...' message, never a crash."""
        server = self._server()
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("connection refused")
        with patch("pry_mcp.fallback_server.get_client", return_value=mock_client):
            result = await server.call_tool("pry_scrape", {"url": "https://example.com"})
        # Structured MCP tool error: isError=True + {"error", "code"} payload.
        assert result["isError"] is True
        text = result["content"][0]["text"]
        assert "Would call POST /v1/scrape" in text
        assert "Live execution unavailable" in text
        assert json.loads(text)["code"] == "API_UNAVAILABLE"

    async def test_unwired_tool_returns_readable_message(self) -> None:
        server = self._server()
        result = await server.call_tool("pry_unknown", {})
        # Unwired tools are tool errors with a structured payload.
        assert result["isError"] is True
        text = result["content"][0]["text"]
        assert "not yet wired" in text
        assert json.loads(text)["code"] == "TOOL_NOT_WIRED"
