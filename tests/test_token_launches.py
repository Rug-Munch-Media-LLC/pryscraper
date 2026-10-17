# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for crypto_market.token_launches (mocked httpx — no live network).

Covers DexScreener/CoinGecko normalization into the shared schema, chain
filtering, ``min_age_minutes`` filtering, in-memory caching, rate-limit
backoff, and the never-raise contract (HTTP errors, timeouts, bad JSON,
invalid chain all yield an empty list).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from crypto_market import get_chain_context, get_new_pairs, get_new_tokens, get_trending_tokens
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


# ── fixtures ────────────────────────────────────────────────────────────


def _profile(chain: str = "solana", address: str = "tok1") -> dict[str, Any]:
    return {
        "chainId": chain,
        "tokenAddress": address,
        "createdAt": 1_750_000_000_000,
        "url": f"https://dexscreener.com/{chain}/{address}",
        "links": [],
        "audits": [],
    }


def _pair(
    chain: str = "solana",
    base: str = "tok1",
    pair: str = "pair1",
    created: int = 1_750_000_100_000,
    price: float | None = 1.5,
    liquidity: float = 100_000.0,
    volume: float = 50_000.0,
    price_change: float = 2.5,
) -> dict[str, Any]:
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


def _cmc_new_page() -> str:
    """CoinMarketCap /new/ page with a ``__NEXT_DATA__`` coin row."""
    data = {
        "props": {
            "initialState": {
                "cryptocurrency": {
                    "listingLatest": {
                        "data": [
                            {
                                "id": 9001,
                                "name": "Fresh Token",
                                "symbol": "FRESH",
                                "slug": "fresh-token",
                                "platform": {"id": "solana"},
                                "date_added": "2026-08-15T00:00:00.000Z",
                                "quote": {
                                    "USD": {
                                        "price": 0.02,
                                        "volume_24h": 1000.0,
                                        "percent_change_24h": 5.0,
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        }
    }
    return (
        '<html><head></head><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></body></html>"
    )


def _birdeye_tokenlist(chain: str) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "tokens": [
                {
                    "address": "bird1",
                    "symbol": "BIRD",
                    "name": "Birdeye Coin",
                    "liquidity": 25_000.0,
                    "v24hUSD": 8_000.0,
                    "v24hChangePercent": 12.5,
                    "lastTradeUnixTime": 1_750_000_000_000,
                }
            ],
            "total": 1,
        },
    }


def _assert_schema(entry: dict[str, Any]) -> None:
    assert set(entry) == SCHEMA_KEYS
    assert isinstance(entry["price_usd"], float)
    assert isinstance(entry["liquidity_usd"], float)
    assert isinstance(entry["volume_24h_usd"], float)
    assert isinstance(entry["price_change_24h_pct"], float)


# ── get_new_tokens: normalization ───────────────────────────────────────


@respx.mock
async def test_get_new_tokens_normalizes_dexscreener() -> None:
    _mock_profiles(_profile(address="tok1"))
    _mock_tokens("solana", _pair(base="tok1", pair="pair1"))

    result = await get_new_tokens(chain="solana", limit=10)

    assert len(result) == 1
    entry = result[0]
    _assert_schema(entry)
    assert entry["chain"] == "solana"
    assert entry["address"] == "tok1"
    assert entry["symbol"] == "TKN"
    assert entry["name"] == "Token tok1"
    assert entry["pair_address"] == "pair1"
    assert entry["created_at_utc"] == "2025-06-15T15:08:20+00:00"
    assert entry["price_usd"] == 1.5
    assert entry["liquidity_usd"] == 100_000.0
    assert entry["volume_24h_usd"] == 50_000.0
    assert entry["price_change_24h_pct"] == 2.5
    assert entry["source"] == "dexscreener"


@respx.mock
async def test_get_new_tokens_sorts_newest_first_and_limits() -> None:
    _mock_profiles(
        _profile(address="old"),
        _profile(address="new"),
    )
    _mock_tokens(
        "solana",
        _pair(base="old", pair="p-old", created=1_750_000_000_000),
        _pair(base="new", pair="p-new", created=1_750_000_900_000),
    )

    result = await get_new_tokens(chain="solana", limit=1)

    expected = ["new"]
    assert [entry["address"] for entry in result] == expected


@respx.mock
async def test_get_new_tokens_best_pair_per_token() -> None:
    _mock_profiles(_profile(address="tok1"))
    _mock_tokens(
        "solana",
        _pair(base="tok1", pair="low-liq", liquidity=1_000.0),
        _pair(base="tok1", pair="high-liq", liquidity=900_000.0),
    )

    result = await get_new_tokens(chain="solana")

    assert len(result) == 1
    assert result[0]["pair_address"] == "high-liq"


# ── get_new_tokens: chain filtering ─────────────────────────────────────


@respx.mock
async def test_get_new_tokens_chain_filter() -> None:
    _mock_profiles(
        _profile(chain="solana", address="sol-tok"),
        _profile(chain="ethereum", address="eth-tok"),
    )
    _mock_tokens("solana", _pair(chain="solana", base="sol-tok", pair="p-sol"))
    _mock_tokens("ethereum", _pair(chain="ethereum", base="eth-tok", pair="p-eth"))

    solana_only = await get_new_tokens(chain="solana")
    expected = ["sol-tok"]
    assert [entry["address"] for entry in solana_only] == expected

    all_chains = await get_new_tokens(chain="all")
    expected_2 = {"solana", "ethereum"}
    assert {entry["chain"] for entry in all_chains} == expected_2


@respx.mock
async def test_get_new_tokens_unsupported_chain_returns_empty_without_network() -> None:
    result = await get_new_tokens(chain="tron")
    assert result == []
    assert respx.calls.call_count == 0


# ── get_new_tokens: min_age_minutes filtering ───────────────────────────


@respx.mock
async def test_get_new_tokens_min_age_filters() -> None:
    # 1_500_000_000_000 ms == 2017-07-14 ≈ 4.8M minutes old (deterministic gap).
    _mock_profiles(_profile(address="tok1"))
    _mock_tokens("solana", _pair(base="tok1", pair="p1", created=1_500_000_000_000))

    unfiltered = await get_new_tokens(chain="solana", min_age_minutes=0)
    assert len(unfiltered) == 1

    filtered = await get_new_tokens(chain="solana", min_age_minutes=5_000_000)
    assert filtered == []


# ── get_new_pairs ───────────────────────────────────────────────────────


@respx.mock
async def test_get_new_pairs_returns_all_pairs_deduped_sorted() -> None:
    _mock_profiles(_profile(address="tok1"))
    _mock_tokens(
        "solana",
        _pair(base="tok1", pair="p-old", created=1_750_000_000_000),
        _pair(base="tok1", pair="p-new", created=1_750_000_800_000),
        _pair(base="tok1", pair="p-new", created=1_750_000_800_000),  # duplicate
    )

    result = await get_new_pairs(chain="solana")

    expected = ["p-new", "p-old"]
    assert [entry["pair_address"] for entry in result] == expected


# ── get_trending_tokens ─────────────────────────────────────────────────


@respx.mock
async def test_get_trending_tokens_dexscreener_primary() -> None:
    respx.get(f"{DEX}/token-boosts/latest/v1").mock(
        return_value=httpx.Response(200, json=[_profile(address="boost-tok")])
    )
    _mock_tokens("solana", _pair(base="boost-tok", pair="p-boost"))

    result = await get_trending_tokens(chain="solana")

    assert len(result) == 1
    assert result[0]["address"] == "boost-tok"
    assert result[0]["source"] == "dexscreener"


@respx.mock
async def test_get_trending_tokens_coingecko_fallback() -> None:
    respx.get(f"{DEX}/token-boosts/latest/v1").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{CG}/search/trending").mock(
        return_value=httpx.Response(
            200,
            json={"coins": [{"item": {"id": "pixel-token", "name": "Pixel", "symbol": "PXL"}}]},
        )
    )
    respx.get(url__startswith=f"{CG}/coins/markets").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "pixel-token",
                    "symbol": "PXL",
                    "name": "Pixel",
                    "current_price": 0.42,
                    "total_volume": 12_000.0,
                    "price_change_percentage_24h": -3.1,
                }
            ],
        )
    )
    respx.get(url__startswith=f"{CG}/coins/list").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "pixel-token", "symbol": "pxl", "platforms": {"solana": "addr123"}}],
        )
    )

    result = await get_trending_tokens(chain="solana")

    assert len(result) == 1
    entry = result[0]
    _assert_schema(entry)
    assert entry["chain"] == "solana"
    assert entry["symbol"] == "PXL"
    assert entry["price_usd"] == 0.42
    assert entry["volume_24h_usd"] == 12_000.0
    assert entry["source"] == "coingecko"


# ── never-raise contract ────────────────────────────────────────────────


@respx.mock
async def test_empty_on_server_error() -> None:
    # A profile is required, else the token fetch is skipped and the 500 never runs.
    _mock_profiles(_profile(address="tok1"))
    respx.get(url__startswith=f"{DEX}/tokens/v1/").mock(
        return_value=httpx.Response(500, text="boom")
    )

    assert await get_new_tokens() == []
    assert await get_new_pairs() == []
    assert await get_trending_tokens() == []
    assert respx.calls.call_count == 3


@respx.mock
async def test_empty_on_network_error() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    assert await get_new_tokens(chain="solana") == []
    assert await get_new_pairs(chain="solana") == []
    assert respx.calls.call_count == 2


@respx.mock
async def test_empty_on_timeout() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        side_effect=httpx.ReadTimeout("read timed out")
    )

    assert await get_new_tokens(chain="solana") == []
    assert respx.calls.call_count == 2


@respx.mock
async def test_empty_on_bad_json() -> None:
    respx.get(f"{DEX}/token-profiles/latest/v1").mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>")
    )

    assert await get_new_tokens() == []
    assert await get_new_pairs() == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_get_new_tokens_falls_back_to_coingecko_when_dexscreener_empty() -> None:
    _mock_profiles()  # empty profiles -> DexScreener yields nothing
    respx.get(url__startswith=f"{CG}/coins/markets").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "fresh-coin",
                    "symbol": "FRESH",
                    "name": "Fresh Coin",
                    "current_price": 0.01,
                    "total_volume": 500.0,
                    "price_change_percentage_24h": 10.0,
                }
            ],
        )
    )
    respx.get(url__startswith=f"{CG}/coins/list").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "fresh-coin", "symbol": "fresh", "platforms": {"solana": "addr"}}],
        )
    )

    result = await get_new_tokens(chain="solana")

    assert len(result) == 1
    assert result[0]["source"] == "coingecko"
    assert result[0]["chain"] == "solana"  # attributed via platform map
    assert result[0]["address"] == "fresh-coin"


# ── CoinMarketCap new-listings fallback ────────────────────────────────


@respx.mock
async def test_get_new_tokens_cmc_fallback_when_others_empty() -> None:
    _mock_profiles()  # empty DexScreener profiles
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(200, text=_cmc_new_page()))

    result = await get_new_tokens(chain="solana")

    assert len(result) == 1
    entry = result[0]
    _assert_schema(entry)
    assert entry["source"] == "coinmarketcap"
    assert entry["chain"] == "solana"  # platform.id "solana" attributed
    assert entry["symbol"] == "FRESH"
    assert entry["name"] == "Fresh Token"
    assert entry["price_usd"] == 0.02
    assert entry["volume_24h_usd"] == 1000.0
    assert entry["created_at_utc"] == "2026-08-15T00:00:00+00:00"


@respx.mock
async def test_get_new_tokens_cmc_bad_html_returns_empty() -> None:
    _mock_profiles()
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(200, text="<html>no data</html>"))

    assert await get_new_tokens(chain="solana") == []
    assert respx.calls.call_count == 3


@respx.mock
async def test_get_new_tokens_cmc_http_error_returns_empty() -> None:
    _mock_profiles()
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(403))

    assert await get_new_tokens(chain="solana") == []
    assert respx.calls.call_count == 3


# ── Birdeye token list fallback ────────────────────────────────────────


@respx.mock
async def test_get_new_tokens_birdeye_fallback_when_others_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BIRDEYE_API_KEY", "test-key")
    _mock_profiles()
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(200, text="<html>no data</html>"))
    respx.get(url__startswith=BIRDEYE).mock(
        return_value=httpx.Response(200, json=_birdeye_tokenlist("solana"))
    )

    result = await get_new_tokens(chain="solana")

    assert len(result) == 1
    entry = result[0]
    _assert_schema(entry)
    assert entry["source"] == "birdeye"
    assert entry["chain"] == "solana"
    assert entry["symbol"] == "BIRD"
    assert entry["liquidity_usd"] == 25_000.0
    assert entry["volume_24h_usd"] == 8_000.0
    assert entry["price_change_24h_pct"] == 12.5


@respx.mock
async def test_get_new_tokens_birdeye_requires_api_key() -> None:
    _mock_profiles()
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(200, text="<html>no data</html>"))
    # No PRY_BIRDEYE_API_KEY set -> Birdeye is skipped without a network call.
    assert await get_new_tokens(chain="solana") == []
    assert not any(str(c.request.url).startswith(BIRDEYE) for c in respx.calls)


@respx.mock
async def test_get_new_tokens_birdeye_sends_chain_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BIRDEYE_API_KEY", "test-key")
    _mock_profiles()
    respx.get(url__startswith=f"{CG}/coins/markets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(url=CMC_NEW).mock(return_value=httpx.Response(200, text="<html>no data</html>"))
    route = respx.get(url__startswith=BIRDEYE).mock(
        return_value=httpx.Response(200, json=_birdeye_tokenlist("solana"))
    )

    await get_new_tokens(chain="solana")

    request = route.calls.last.request
    assert request.headers.get("x-api-key") == "test-key"
    assert request.headers.get("x-chain") == "solana"


# ── rate-limit backoff ──────────────────────────────────────────────────


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


# ── caching ─────────────────────────────────────────────────────────────


@respx.mock
async def test_results_cached_within_ttl() -> None:
    profiles_route = _mock_profiles(_profile(address="tok1"))
    _mock_tokens("solana", _pair(base="tok1", pair="p1"))

    first = await get_new_tokens(chain="solana", limit=5)
    second = await get_new_tokens(chain="solana", limit=5)

    assert first == second
    assert profiles_route.call_count == 1


# ── DefiLlama chain context ─────────────────────────────────────────────


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


# ── package exports ─────────────────────────────────────────────────────


def test_crypto_market_package_exports() -> None:
    import crypto_market

    for name in ("get_new_tokens", "get_new_pairs", "get_trending_tokens", "get_chain_context"):
        assert name in crypto_market.__all__
        assert callable(getattr(crypto_market, name))


def test_supported_chains_constant() -> None:
    expected = ("ethereum", "solana", "base", "bsc", "arbitrum", "polygon")
    assert expected == SUPPORTED_CHAINS
