"""Tests for the restored ``datasets.crypto_market`` dataset package.

Covers the three public submodules behind ``/v1/crypto/token-launches``,
``/v1/crypto/cex-listings`` and ``/v1/crypto/token-security``: happy-path
return shapes, empty-on-upstream-500, empty-on-timeout, and the router
answering 200 (never 502) when upstreams are down.

All HTTP is mocked with respx — no live network.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import httpx
import pytest
import respx

from datasets.crypto_market import (
    get_listing_signals,
    get_new_pairs,
    get_new_tokens,
    get_trending_tokens,
    scan_token,
    token_launches as dataset_launches,
)
from tests.crypto_market_support import (  # noqa: F401 — fixtures for this module
    ALL_HTTPS,
    LAUNCH_KEYS,
    _fast_retries,
    client,
    mock_dexscreener,
)


def test_package_exports_public_contract() -> None:
    assert dataset_launches.get_new_tokens is get_new_tokens
    assert callable(get_new_pairs)
    assert callable(get_trending_tokens)
    assert callable(get_listing_signals)
    assert callable(scan_token)


@respx.mock
async def test_new_tokens_happy_path_shape() -> None:
    mock_dexscreener()
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


def test_token_launches_route_returns_200_with_documented_shape() -> None:
    with respx.mock:
        mock_dexscreener()
        launches = client().get("/v1/crypto/token-launches", params={"chain": "solana"})
        assert launches.status_code == 200
        body = launches.json()
        assert body["success"] is True
        assert body["kind"] == "tokens"
        assert set(body) == {"success", "data", "chain", "kind"}
        assert body["data"][0].keys() >= LAUNCH_KEYS


def test_cex_listings_route_shape() -> None:
    with respx.mock:
        mock_dexscreener()
        cex = client().get("/v1/crypto/cex-listings", params={"lookback_hours": 24})
        assert cex.status_code == 200
        assert set(cex.json()) == {"success", "data", "lookback_hours"}


def test_token_security_route_shape() -> None:
    with respx.mock:
        respx.route(url__regex=ALL_HTTPS).mock(return_value=httpx.Response(500))
        sec = client().get(
            "/v1/crypto/token-security/ethereum/0x0000000000000000000000000000000000000001"
        )
        assert sec.status_code == 200
        assert sec.json()["success"] is True
        assert "risk_score" in sec.json()["data"]


def test_routes_stay_200_when_upstreams_are_down() -> None:
    with respx.mock:
        respx.route(url__regex=ALL_HTTPS).mock(return_value=httpx.Response(503, text="unavailable"))
        api = client()
        for url in (
            "/v1/crypto/token-launches",
            "/v1/crypto/cex-listings",
            "/v1/crypto/token-security/solana/So11111111111111111111111111111111111111112",
        ):
            resp = api.get(url)
            assert resp.status_code == 200, url
            assert resp.json()["success"] is True


def test_route_degrades_with_availability_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing submodule yields 200 + available=false, never a 502."""
    import pry.api.routers.data.crypto_market as router_mod

    monkeypatch.setattr(router_mod, "_crypto_module", lambda _name: None)
    resp = client().get("/v1/crypto/token-launches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["data"] == []
    assert body["reason"]
