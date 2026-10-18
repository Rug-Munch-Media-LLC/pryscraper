"""Tests for the restored ``datasets.crypto_market`` dataset package.

Covers the three public submodules behind ``/v1/crypto/token-launches``,
``/v1/crypto/cex-listings`` and ``/v1/crypto/token-security``: happy-path
return shapes, empty-on-upstream-500, empty-on-timeout, and the router
answering 200 (never 502) when upstreams are down.

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crypto_market._http as cm_http
from crypto_market.token_launches import _clear_cache
from datasets.crypto_market import (
    get_listing_signals,
    get_new_pairs,
    get_new_tokens,
    get_trending_tokens,
    scan_token,
    token_launches as dataset_launches,
)
from pry.api.routers.data.crypto_market import router as crypto_router

DEX = "https://api.dexscreener.com"
ALL_HTTPS = r"^https://"

LAUNCH_KEYS = {
    "chain",
    "address",
    "symbol",
    "name",
    "created_at",
    "liquidity_usd",
    "volume_24h_usd",
}


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Zero out backoff so failure tests are instant; clear the result cache."""
    monkeypatch.setattr(cm_http, "RETRY_BASE", 0.0)
    monkeypatch.setattr(cm_http, "MAX_BACKOFF", 0.0)
    for env in ("COINGECKO_API_KEY", "PRY_COINGECKO_API_KEY", "PRY_BIRDEYE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    _clear_cache()
    yield
    _clear_cache()


def _profile(address: str = "tok1", chain: str = "solana") -> dict[str, Any]:
    return {"chainId": chain, "tokenAddress": address, "url": "https://dexscreener.com"}


def _pair(address: str = "tok1", pair: str = "pair1") -> dict[str, Any]:
    return {
        "chainId": "solana",
        "pairAddress": pair,
        "baseToken": {"address": address, "name": "Token One", "symbol": "TKN"},
        "priceUsd": "1.5",
        "liquidity": {"usd": 100_000.0},
        "volume": {"h24": 50_000.0},
        "priceChange": {"h24": 2.5},
        "pairCreatedAt": 1_750_000_100_000,
    }


def _mock_dexscreener() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        return_value=httpx.Response(200, json=[_profile()])
    )
    respx.get(url__startswith=f"{DEX}/tokens/v1/solana/").mock(
        return_value=httpx.Response(200, json={"pairs": [_pair()]})
    )
    respx.get(f"{DEX}/token-boosts/latest/v1").mock(
        return_value=httpx.Response(200, json=[_profile()])
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(crypto_router)
    return TestClient(app)


# ── dataset facade ──────────────────────────────────────────────────────


def test_package_exports_public_contract() -> None:
    assert dataset_launches.get_new_tokens is get_new_tokens
    assert callable(get_new_pairs)
    assert callable(get_trending_tokens)
    assert callable(get_listing_signals)
    assert callable(scan_token)


@respx.mock
async def test_new_tokens_happy_path_shape() -> None:
    _mock_dexscreener()
    items = await get_new_tokens(chain="solana", limit=10)
    assert len(items) == 1
    assert items[0].keys() >= LAUNCH_KEYS
    assert items[0]["created_at"] == items[0]["created_at_utc"]
    assert items[0]["address"] == "tok1"


@respx.mock
async def test_empty_on_upstream_500() -> None:
    respx.route(url__regex=ALL_HTTPS).mock(return_value=httpx.Response(500, text="boom"))
    assert await get_new_tokens(chain="solana") == []
    assert await get_new_pairs(chain="solana") == []
    assert await get_trending_tokens(chain="solana") == []


@respx.mock
async def test_empty_on_timeout() -> None:
    respx.route(url__regex=ALL_HTTPS).mock(side_effect=httpx.ReadTimeout("upstream timed out"))
    assert await get_new_tokens(chain="solana") == []
    assert await get_listing_signals(exchanges=["binance"]) == []


@respx.mock
async def test_token_security_degrades_without_raising() -> None:
    respx.route(url__regex=ALL_HTTPS).mock(return_value=httpx.Response(500))
    result = await scan_token("ethereum", "0x0000000000000000000000000000000000000001")
    assert result["risk_level"] == result["verdict"]
    assert result["source"] == "heuristic"
    assert "risk_score" in result
    assert "flags" in result


# ── HTTP routes ─────────────────────────────────────────────────────────


def test_routes_return_200_with_documented_shape() -> None:
    with respx.mock:
        _mock_dexscreener()
        client = _client()
        launches = client.get("/v1/crypto/token-launches", params={"chain": "solana"})
        assert launches.status_code == 200
        body = launches.json()
        assert body["success"] is True
        assert body["kind"] == "tokens"
        assert set(body) == {"success", "data", "chain", "kind"}
        assert body["data"][0].keys() >= LAUNCH_KEYS

        cex = client.get("/v1/crypto/cex-listings", params={"lookback_hours": 24})
        assert cex.status_code == 200
        assert set(cex.json()) == {"success", "data", "lookback_hours"}

        sec = client.get(
            "/v1/crypto/token-security/ethereum/0x0000000000000000000000000000000000000001"
        )
        assert sec.status_code == 200
        assert sec.json()["success"] is True
        assert "risk_score" in sec.json()["data"]


def test_routes_stay_200_when_upstreams_are_down() -> None:
    with respx.mock:
        respx.route(url__regex=ALL_HTTPS).mock(return_value=httpx.Response(503, text="unavailable"))
        client = _client()
        for url in (
            "/v1/crypto/token-launches",
            "/v1/crypto/cex-listings",
            "/v1/crypto/token-security/solana/So11111111111111111111111111111111111111112",
        ):
            resp = client.get(url)
            assert resp.status_code == 200, url
            assert resp.json()["success"] is True


def test_route_degrades_with_availability_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing submodule yields 200 + available=false, never a 502."""
    import pry.api.routers.data.crypto_market as router_mod

    monkeypatch.setattr(router_mod, "_crypto_module", lambda _name: None)
    resp = _client().get("/v1/crypto/token-launches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["data"] == []
    assert body["reason"]
