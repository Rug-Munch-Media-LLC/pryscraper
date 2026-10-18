"""Shared fixtures and payload builders for the crypto_market dataset tests."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crypto_market._http as cm_http
from crypto_market.token_launches import _clear_cache
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


def profile(address: str = "tok1", chain: str = "solana") -> dict[str, Any]:
    return {"chainId": chain, "tokenAddress": address, "url": "https://dexscreener.com"}


def pair(address: str = "tok1", pair_address: str = "pair1") -> dict[str, Any]:
    return {
        "chainId": "solana",
        "pairAddress": pair_address,
        "baseToken": {"address": address, "name": "Token One", "symbol": "TKN"},
        "priceUsd": "1.5",
        "liquidity": {"usd": 100_000.0},
        "volume": {"h24": 50_000.0},
        "priceChange": {"h24": 2.5},
        "pairCreatedAt": 1_750_000_100_000,
    }


def mock_dexscreener() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        return_value=httpx.Response(200, json=[profile()])
    )
    respx.get(url__startswith=f"{DEX}/tokens/v1/solana/").mock(
        return_value=httpx.Response(200, json={"pairs": [pair()]})
    )
    respx.get(f"{DEX}/token-boosts/latest/v1").mock(
        return_value=httpx.Response(200, json=[profile()])
    )


def client() -> TestClient:
    app = FastAPI()
    app.include_router(crypto_router)
    return TestClient(app)
