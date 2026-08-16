# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP server quality audit tests.

Covers four layers of the MCP surface:

1. **Tool metadata** — every ``PRY_TOOLS`` entry must have an example-rich
   description, a complete ``inputSchema`` (every param typed + described +
   required flagged), an ``outputSchema``, and the MCP 2025-11-25 annotation
   triple (``readOnlyHint`` / ``destructiveHint`` / ``idempotentHint``).
2. **Round-trip ``tools/call``** — every tool, called through the fallback
   server with a mocked domain module (or mocked REST proxy), returns a
   JSON-RPC success; when the module is absent the readable "not available"
   message is verified.
3. **Streamable HTTP transport compliance** (``pry_mcp.app``) — JSON vs SSE
   Accept handling, ``406`` on GET without SSE Accept, JSON-RPC error objects
   (``-32700`` parse, ``-32600`` invalid request, ``-32601`` method-not-found),
   notifications answered with ``202``, and ``Mcp-Session-Id`` lifecycle.
4. **Tool-count consistency** — ``PRY_TOOLS`` must stay in sync with
   ``server.json`` / ``glama.json`` / ``pulsemcp.json`` / ``llms.txt`` /
   ``smithery.yaml`` (all currently 50).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import types
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from pry_mcp import PRY_TOOLS, make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor
from pry_mcp.tools import PRY_TOOL_NAMES

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]

# ────────────────────────────────────────────────────────────────────────────
# Per-tool round-trip table
# ────────────────────────────────────────────────────────────────────────────

# Domain-dispatched tools: name -> (module to patch, function names to mock,
# sample arguments). The module names match the guarded imports in
# pry_mcp.tools; all 10 data-domain packages have landed, so these run the
# success path with mocked modules (no network).
_DOMAIN_TOOLS: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    "pry_token_launches": (
        "crypto_market.token_launches",
        ("get_new_tokens", "get_new_pairs", "get_trending_tokens"),
        {"chain": "solana", "limit": 5},
    ),
    "pry_cex_listings": (
        "crypto_market.cex_listings",
        ("get_listing_signals",),
        {"exchanges": ["binance"], "lookback_hours": 24},
    ),
    "pry_token_security": (
        "crypto_market.token_security",
        ("scan_token",),
        {"chain": "solana", "address": "So11111111111111111111111111111111111111112"},
    ),
    "pry_odds": ("sports_data.odds", ("get_odds",), {"sport": "basketball_nba", "limit": 5}),
    "pry_arbitrage": (
        "sports_data.arbitrage",
        ("find_arbitrage",),
        {"sport": "all", "min_yield_pct": 0.5},
    ),
    "pry_plus_ev": (
        "sports_data.ev",
        ("find_plus_ev",),
        {"sharp_book": "pinnacle", "min_ev_pct": 2.0},
    ),
    "pry_props": (
        "sports_data.props",
        ("get_player_props",),
        {"player": "LeBron James", "sport": "basketball_nba", "limit": 5},
    ),
    "pry_injuries": (
        "sports_data.injuries",
        ("get_injuries",),
        {"sport": "basketball_nba", "team": "all"},
    ),
    "pry_live_odds": ("sports_data.live", ("get_live_odds",), {"sport": "all", "limit": 5}),
    "pry_scores": (
        "sports_data.scores",
        ("get_scores",),
        {"sport": "basketball_nba", "date": "today"},
    ),
    "pry_historical_odds": (
        "sports_data.historical",
        ("get_historical_odds",),
        {"sport": "basketball_nba", "event_id": "e1", "date": "2026-08-01", "limit": 5},
    ),
    "pry_betting_percentages": (
        "sports_data.betting_percentages",
        ("get_betting_percentages",),
        {"event_id": "e1", "sport": "basketball_nba", "limit": 5},
    ),
    "pry_sharp_consensus": (
        "sports_data.sharp_consensus",
        ("get_sharp_consensus",),
        {"event_id": "e1", "sharp_books": ["pinnacle", "circa"], "limit": 5},
    ),
    "pry_alerts": (
        "sports_data.alerts",
        ("list_alerts",),
        {"alert_type": "line_move", "sport": "all", "limit": 5},
    ),
    "pry_weather": (
        "climate_data.weather",
        ("get_forecast",),
        {"location": "38.9072,-77.0369", "forecast_days": 2},
    ),
    "pry_agri": (
        "climate_data.agri",
        ("get_crop_prices",),
        {"crop": "corn", "region": "Iowa", "limit": 5},
    ),
    "pry_papers": (
        "research_data.academic",
        ("search_papers",),
        {"query": "retrieval augmented generation", "limit": 5},
    ),
    "pry_domain": (
        "research_data.domain",
        ("whois_lookup",),
        {"domain": "example.com", "include_tech": True},
    ),
    "pry_amazon_product": ("marketplace.amazon", ("get_product",), {"asin": "B08N5WRWNW"}),
    "pry_amazon_search": (
        "marketplace.amazon",
        ("search_products",),
        {"query": "wireless keyboard", "limit": 5},
    ),
    "pry_walmart_product": (
        "marketplace.walmart",
        ("get_product",),
        {"product_id": "4JH7P89H7X5P"},
    ),
    "pry_tiktok_trending": ("marketplace.tiktok_shop", ("get_trending",), {"limit": 5}),
    "pry_legal_dockets": (
        "legal_docs.dockets",
        ("search_dockets",),
        {"query": "OpenAI copyright", "limit": 2},
    ),
    "pry_legal_sec": (
        "legal_docs.sec_filings",
        ("search_filings",),
        {"ticker": "AAPL", "form_type": "8-K", "limit": 2},
    ),
    "pry_legal_sanctions": (
        "legal_docs.sanctions",
        ("screen_name",),
        {"name": "Vladimir Potanin"},
    ),
    "pry_realestate_search": (
        "real_estate.listings",
        ("search_listings",),
        {"location": "Austin, TX", "status": "for_sale", "limit": 2},
    ),
    "pry_jobs_list": (
        "jobs.ats",
        ("list_jobs",),
        {"company": "stripe", "board": "greenhouse", "limit": 2},
    ),
    "pry_jobs_salary": (
        "jobs.salary",
        ("get_salary",),
        {"company": "google", "role": "software_engineer"},
    ),
    "pry_flights_grid": (
        "travel.flights",
        ("cheapest_date_grid",),
        {"origin": "JFK", "dest": "CDG", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    ),
    "pry_hotel_rates": (
        "travel.hotels",
        ("get_hotel_rates",),
        {"hotel_name": "Ritz Paris", "checkin": "2026-09-10", "checkout": "2026-09-14"},
    ),
    "pry_serp": ("attention.serp", ("serp",), {"q": "best wireless keyboard", "num": 5}),
    "pry_trends": (
        "attention.trends",
        ("trend_interest",),
        {"keyword": "AI agents", "timeframe": "today 3-m"},
    ),
    "pry_places_search": (
        "local_data.places",
        ("search_places",),
        {"query": "taco", "location": "Austin TX", "limit": 2},
    ),
    "pry_reviews": (
        "local_data.reviews",
        ("get_reviews",),
        {"place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4", "source": "google", "limit": 2},
    ),
    # gov_data / ip_data resolve candidate function names via __import__.
    "pry_procurement": (
        "gov_data",
        ("search_opportunities",),
        {"query": "cybersecurity", "limit": 2},
    ),
    "pry_recalls": ("gov_data", ("search_recalls",), {"query": "e-bike battery", "limit": 2}),
    "pry_patents": ("ip_data", ("search_patents",), {"query": "blockchain identity", "limit": 2}),
    "pry_trademarks": (
        "ip_data",
        ("search_trademarks",),
        {"query": "RugMunch", "limit": 2},
    ),
}

# REST-proxy tools: name -> sample arguments. The fallback server calls the
# Pry HTTP API via httpx; tests mock httpx.AsyncClient so no network is used.
_REST_PROXY_TOOLS: dict[str, dict[str, Any]] = {
    "pry_scrape": {"url": "https://example.com"},
    "pry_crawl": {"url": "https://example.com", "max_pages": 5},
    "pry_extract": {
        "url": "https://example.com/products",
        "schema": {
            "name": "product",
            "fields": [{"name": "price", "selector": ".price", "type": "text"}],
        },
    },
    "pry_template": {
        "template_id": "amazon-product",
        "url": "https://www.amazon.com/dp/B08N5WRWNW",
    },
    "pry_search_templates": {"q": "amazon"},
    "pry_monitor": {"name": "price watch", "url": "https://example.com/pricing"},
    "pry_compliance": {"url": "https://example.com"},
    "pry_enrich": {"url": "https://startup.example.com"},
    "pry_parse_document": {"url": "https://example.com/spec.pdf"},
    "pry_screenshot": {"url": "https://example.com/checkout"},
    "pry_x402_pricing": {},
    "pry_referrals": {"category": "proxies"},
}

# Guard: the tables must cover every registered tool, or the audit is broken.
assert set(_DOMAIN_TOOLS) | set(_REST_PROXY_TOOLS) == set(PRY_TOOL_NAMES), (
    "round-trip tables do not cover every PRY_TOOLS entry"
)

_MISSING = object()


@contextmanager
def _patch_module(name: str, module: Any) -> Iterator[None]:
    """Swap ``sys.modules[name]`` for the duration of the test.

    ``module`` may be ``None`` (simulates a module that has not landed yet:
    CPython raises ``ImportError`` for ``from X import Y`` when
    ``sys.modules[X]`` is None) or a fake module object (success path).
    """
    if "." in name:
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


def _fake_module(**attrs: Any) -> types.ModuleType:
    """Build a minimal module object exposing async callables (AsyncMock)."""
    module = types.ModuleType("fake")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _server() -> Any:
    """A fully registered fallback server with the combined tool executor."""
    srv = make_fallback_server(
        base_url="http://mcp-test.invalid",
        tool_executor=combined_tool_executor,
    )
    register_all(srv)
    return srv


@pytest.fixture(autouse=True)
def _clear_hot_tool_cache() -> Iterator[None]:
    """Reset the dispatch-level 10s hot-tool cache before every test.

    ``combined_tool_executor`` memoizes hot tools (odds, serp, ...) for 10
    seconds; without a reset, a success-path test caches a result that a
    later missing-module test would read back instead of the readable
    "not available" message.
    """
    import pry_mcp.fallback_server as _fallback

    _fallback._hot_tool_cache.clear()
    yield
    _fallback._hot_tool_cache.clear()


async def _call(srv: Any, name: str, args: dict[str, Any], req_id: int = 100) -> dict[str, Any]:
    """Issue a ``tools/call`` JSON-RPC request and return the response."""
    resp = await srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert resp is not None
    return resp


# ────────────────────────────────────────────────────────────────────────────
# 1. Tool metadata audit
# ────────────────────────────────────────────────────────────────────────────


class TestToolMetadata:
    """Every PRY_TOOLS entry must meet the 2026 MCP quality bar."""

    def test_tool_count_is_50(self) -> None:
        assert len(PRY_TOOLS) == 50
        assert len(PRY_TOOL_NAMES) == 50
        assert len({t["name"] for t in PRY_TOOLS}) == 50

    @pytest.mark.parametrize("tool_name", sorted(PRY_TOOL_NAMES))
    def test_tools_list_metadata(self, tool_name: str) -> None:
        srv = _server()
        resp = asyncio.run(srv.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
        assert "error" not in resp
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert tool_name in tools, f"tools/list missing {tool_name}"
        tool = tools[tool_name]

        # (a) example-rich description: WHAT + WHEN + concrete example.
        desc = tool["description"]
        assert desc, f"{tool_name}: empty description"
        assert desc.strip(), f"{tool_name}: blank description"
        assert len(desc.split()) >= 20, (
            f"{tool_name}: description too thin ({len(desc.split())} words)"
        )
        assert any(
            marker in desc for marker in ("e.g.", "example", "Example", " like ", "such as")
        ), f"{tool_name}: description lacks a concrete example"

        # (b) complete inputSchema: object, every param typed + described,
        #     required flags reference real properties.
        schema = tool["inputSchema"]
        assert schema["type"] == "object", f"{tool_name}: inputSchema not object"
        props = schema["properties"]
        for pname, p in props.items():
            assert "type" in p, f"{tool_name}.{pname}: missing type"
            assert p.get("description"), f"{tool_name}.{pname}: missing description"
        for req in schema.get("required", []):
            assert req in props, f"{tool_name}: required {req} not in properties"

        # (c) outputSchema present.
        assert "outputSchema" in tool, f"{tool_name}: missing outputSchema"

        # (d) annotations triple present and coherent.
        ann = tool.get("annotations", {})
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint"):
            assert key in ann, f"{tool_name}: missing annotation {key}"
        if tool_name == "pry_monitor":
            assert ann["readOnlyHint"] is False, "pry_monitor mutates server state"
            assert ann["idempotentHint"] is False, "pry_monitor creates a new monitor per call"
            assert ann["destructiveHint"] is False, "pry_monitor never deletes data"

    def test_state_mutating_tool_annotations(self) -> None:
        """Only pry_monitor may opt out of the read-only default."""
        for tool in PRY_TOOLS:
            if tool["name"] == "pry_monitor":
                continue
            ann = tool["annotations"]
            assert ann["readOnlyHint"] is True, f"{tool['name']} should be read-only"
            assert ann["destructiveHint"] is False, f"{tool['name']} should be non-destructive"
            assert ann["idempotentHint"] is True, f"{tool['name']} should be idempotent"


# ────────────────────────────────────────────────────────────────────────────
# 2. Round-trip tools/call for every tool
# ────────────────────────────────────────────────────────────────────────────


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
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        with patch("pry_mcp.fallback_server.httpx.AsyncClient", return_value=mock_client):
            resp = await _call(srv, "pry_scrape", {"url": "https://example.com"})
        assert "error" not in resp
        assert resp["result"]["isError"] is False
        assert "Would call POST /v1/scrape" in resp["result"]["content"][0]["text"]

    async def test_unknown_tool_returns_jsonrpc_error(self) -> None:
        srv = _server()
        resp = await _call(srv, "pry_not_a_real_tool", {})
        assert "error" in resp
        assert resp["error"]["code"] == -32602


# ────────────────────────────────────────────────────────────────────────────
# 3. Streamable HTTP transport compliance
# ────────────────────────────────────────────────────────────────────────────


def _make_app() -> Any:
    from pry_mcp.app import create_mcp_app

    return create_mcp_app(get_server=lambda: _server())


@pytest.fixture
def mcp_client() -> Iterator[TestClient]:
    """TestClient over the standalone MCP app with a fresh server per test."""
    from pry_mcp.app import _MCP_SESSIONS

    _MCP_SESSIONS.clear()
    with TestClient(_make_app()) as client:
        yield client
    _MCP_SESSIONS.clear()


class TestTransportCompliance:
    """Streamable HTTP spec compliance for POST / and GET /."""

    def test_post_json_accept_returns_json_rpc(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert len(body["result"]["tools"]) == 50

    def test_post_sse_accept_returns_event_stream(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = resp.text
        assert "event: message" in text
        assert '"jsonrpc":"2.0"' in text or '"jsonrpc": "2.0"' in text
        assert '"result":{}' in text.replace(" ", "") or '"result": {}' in text

    def test_get_without_sse_accept_returns_406(self, mcp_client: TestClient) -> None:
        resp = mcp_client.get("/", headers={"Accept": "application/json"})
        assert resp.status_code == 406

    def test_get_with_sse_accept_opens_stream(self, mcp_client: TestClient) -> None:
        # ``_sse_test_close_after=1`` is the private test hook shared with
        # mcp_sse.py: emit one keepalive and close so the infinite stream can
        # be consumed by ASGITransport-based tests.
        with mcp_client.stream(
            "GET", "/?_sse_test_close_after=1", headers={"Accept": "text/event-stream"}
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
            assert ": ping" in body

    def test_parse_error_returns_32700(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            content="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] is None
        assert body["error"]["code"] == -32700

    def test_invalid_request_returns_32600(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post("/", json={"not": "valid json-rpc"})
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32600

    def test_unknown_method_returns_32601(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 9, "method": "no/such/method"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert "no/such/method" in body["error"]["message"]

    def test_notification_returns_202_empty(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        assert resp.status_code == 202
        assert resp.content == b""

    def test_response_cache_control_no_store(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert "no-store" in resp.headers.get("cache-control", "")


class TestSessionLifecycle:
    """Mcp-Session-Id issuance, validation, and termination."""

    def test_initialize_issues_session_id(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp.status_code == 200
        session_id = resp.headers.get("mcp-session-id")
        assert session_id, "initialize must issue an Mcp-Session-Id"
        assert resp.json()["result"]["protocolVersion"] == "2024-11-05"

    def test_known_session_accepted(self, mcp_client: TestClient) -> None:
        init = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_id = init.headers["mcp-session-id"]
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["result"] == {}

    def test_unknown_session_returns_404(self, mcp_client: TestClient) -> None:
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": "deadbeef"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == -32001

    def test_delete_session_then_404(self, mcp_client: TestClient) -> None:
        init = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_id = init.headers["mcp-session-id"]
        deleted = mcp_client.delete("/", headers={"Mcp-Session-Id": session_id})
        assert deleted.status_code == 200
        resp = mcp_client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 404

    def test_delete_without_session_returns_400(self, mcp_client: TestClient) -> None:
        resp = mcp_client.delete("/")
        assert resp.status_code == 400


# ────────────────────────────────────────────────────────────────────────────
# 4. Tool-count consistency with registry files
# ────────────────────────────────────────────────────────────────────────────


def _find_tools_list(obj: Any) -> list[Any] | None:
    """Recursively find the first ``tools`` list in a registry JSON doc."""
    if isinstance(obj, dict):
        if "tools" in obj and isinstance(obj["tools"], list):
            return obj["tools"]
        for value in obj.values():
            found = _find_tools_list(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_tools_list(value)
            if found is not None:
                return found
    return None


class TestRegistryConsistency:
    """PRY_TOOLS must match every published registry file (currently 50)."""

    @pytest.mark.parametrize("fname", ["server.json", "glama.json", "pulsemcp.json"])
    def test_json_registries_match(self, fname: str) -> None:
        data = json.loads((REPO_ROOT / fname).read_text(encoding="utf-8"))
        tools = _find_tools_list(data)
        assert tools is not None, f"{fname}: no tools list found"
        if fname == "pulsemcp.json":
            names = {t for t in tools if isinstance(t, str)}
        else:
            names = {t["name"] for t in tools if isinstance(t, dict) and "name" in t}
        assert names == set(PRY_TOOL_NAMES), (
            f"{fname} drift: missing={sorted(set(PRY_TOOL_NAMES) - names)} "
            f"extra={sorted(names - set(PRY_TOOL_NAMES))}"
        )

    def test_llms_txt_lists_every_tool(self) -> None:
        text = (REPO_ROOT / "llms.txt").read_text(encoding="utf-8")
        listed = set(re.findall(r"^- \[(pry_[a-z0-9_]+)\]", text, flags=re.MULTILINE))
        assert listed == set(PRY_TOOL_NAMES), (
            f"llms.txt drift: missing={sorted(set(PRY_TOOL_NAMES) - listed)} "
            f"extra={sorted(listed - set(PRY_TOOL_NAMES))}"
        )

    def test_smithery_comment_matches_count(self) -> None:
        text = (REPO_ROOT / "smithery.yaml").read_text(encoding="utf-8")
        assert "Tool count: 50" in text, "smithery.yaml tool-count comment drifted"
