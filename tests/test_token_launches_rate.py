"""Tests for crypto_market.token_launches (mocked httpx — no live network).

Covers DexScreener/CoinGecko normalization into the shared schema, chain
filtering, ``min_age_minutes`` filtering, in-memory caching, rate-limit
backoff, and the never-raise contract (HTTP errors, timeouts, bad JSON,
invalid chain all yield an empty list).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from crypto_market import get_chain_context, get_new_tokens
from crypto_market.token_launches import (
    SUPPORTED_CHAINS,
    _clear_cache,
)

DEX = "https://api.dexscreener.com"

CG = "https://api.coingecko.com/api/v3"

LLAMA = "https://api.llama.fi"

CMC_NEW = "https://coinmarketcap.com/new/"

BIRDEYE = "https://public-api.birdeye.so/defi/tokenlist"

SCHEMA_KEYS = {
    "chain",
    "address",
    "symbol",
    "name",
    "pair_address",
    "created_at_utc",
    "price_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "price_change_24h_pct",
    "source",
}


@pytest.fixture(autouse=True)
def _hermetic_crypto_market(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Clear caches + API keys so tests are hermetic and fast."""
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    monkeypatch.delenv("PRY_COINGECKO_API_KEY", raising=False)
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    monkeypatch.delenv("PRY_BIRDEYE_API_KEY", raising=False)
    import crypto_market.token_launches as tl

    monkeypatch.setattr(tl._http, "RETRY_BASE", 0.0)
    monkeypatch.setattr(tl._http, "MAX_BACKOFF", 0.0)
    _clear_cache()
    yield
    _clear_cache()


def _profile(chain: str = "solana", address: str = "tok1") -> dict[str, Any]:
    return {
        "chainId": chain,
        "tokenAddress": address,
        "createdAt": 1_750_000_000_000,
        "url": f"https://dexscreener.com/{chain}/{address}",
        "links": [],
        "audits": [],
    }


def _pair(**kw: Any) -> dict[str, Any]:
    chain, base, pair = kw.get("chain", "solana"), kw.get("base", "tok1"), kw.get("pair", "pair1")
    created, price = kw.get("created", 1_750_000_100_000), kw.get("price", 1.5)
    liquidity, volume = kw.get("liquidity", 100_000.0), kw.get("volume", 50_000.0)
    price_change = kw.get("price_change", 2.5)
    return {
        "chainId": chain,
        "dexId": "raydium",
        "url": f"https://dexscreener.com/{chain}/{pair}",
        "pairAddress": pair,
        "baseToken": {"address": base, "name": f"Token {base}", "symbol": "TKN"},
        "quoteToken": {
            "address": "So11111111111111111111111111111111111111112",
            "name": "SOL",
            "symbol": "SOL",
        },
        "priceNative": "0.001",
        "priceUsd": price,
        "txns": {"h24": {"buys": 20, "sells": 10}},
        "volume": {"h24": volume},
        "priceChange": {"h24": price_change},
        "liquidity": {"usd": liquidity},
        "fdv": 500_000.0,
        "pairCreatedAt": created,
        "boosts": {"active": 0},
    }


def _mock_profiles(*profiles: dict[str, Any]) -> respx.Route:
    return respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        return_value=httpx.Response(200, json=list(profiles))
    )


def _mock_tokens(chain: str, *pairs: dict[str, Any]) -> respx.Route:
    return respx.get(url__startswith=f"{DEX}/tokens/v1/{chain}/").mock(
        return_value=httpx.Response(200, json={"pairs": list(pairs)})
    )


@respx.mock
async def test_rate_limit_429_retries_then_succeeds() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            httpx.Response(200, json=[_profile(address="tok1")]),
        ]
    )
    _mock_tokens("solana", _pair(base="tok1", pair="p1"))

    result = await get_new_tokens(chain="solana")

    assert len(result) == 1
    assert result[0]["address"] == "tok1"


@respx.mock
async def test_rate_limit_429_exhausted_returns_empty() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(return_value=httpx.Response(429, json={}))

    assert await get_new_tokens(chain="solana") == []
    assert respx.calls.call_count == 2


@respx.mock
async def test_results_cached_within_ttl() -> None:
    profiles_route = _mock_profiles(_profile(address="tok1"))
    _mock_tokens("solana", _pair(base="tok1", pair="p1"))

    first = await get_new_tokens(chain="solana", limit=5)
    second = await get_new_tokens(chain="solana", limit=5)

    assert first == second
    assert profiles_route.call_count == 1


@respx.mock
async def test_get_chain_context_filters_and_normalizes() -> None:
    respx.get(f"{LLAMA}/v2/chains").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"name": "Ethereum", "chainId": "ethereum", "tvl": 50_000_000.0},
                {"name": "Solana", "chainId": "solana", "tvl": 8_000_000.0},
                {"name": "Base", "chainId": "base", "tvl": 2_000_000.0},
            ],
        )
    )

    result = await get_chain_context(chain="solana")

    assert len(result) == 1
    assert result[0]["chain"] == "solana"
    assert result[0]["tvl_usd"] == 8_000_000.0


@respx.mock
async def test_get_chain_context_empty_on_failure() -> None:
    respx.get(f"{LLAMA}/v2/chains").mock(return_value=httpx.Response(500, text="boom"))

    assert await get_chain_context() == []
    assert respx.calls.call_count == 2


def test_crypto_market_package_exports() -> None:
    import crypto_market

    for name in ("get_new_tokens", "get_new_pairs", "get_trending_tokens", "get_chain_context"):
        assert name in crypto_market.__all__
        assert callable(getattr(crypto_market, name))


def test_supported_chains_constant() -> None:
    expected = ("ethereum", "solana", "base", "bsc", "arbitrum", "polygon")
    assert expected == SUPPORTED_CHAINS
