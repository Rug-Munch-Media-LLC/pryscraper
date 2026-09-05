"""CoinGecko providers — new listings and trending (fallback sources).

Keyless free-tier endpoints; ``/coins/list/new`` unlocks with an optional
API key read from the environment. Chain attribution uses the (large,
1h-cached) ``/coins/list`` platform map.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import Any

from crypto_market._cache import COINGECKO_LIST_TTL
from crypto_market._http import _get_json
from crypto_market._normalize import (
    _api_key,
    _created_epoch,
    _entry_age_minutes,
    _f,
    _iso,
)
from crypto_market._registry import COINGECKO_PLATFORMS

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_MARKETS_BATCH = 100  # max ids per /coins/markets call


async def _coingecko_platform_ids() -> dict[str, set[str]]:
    """Map CoinGecko platform -> set of coin ids (/coins/list, cached 1h)."""
    import crypto_market._cache as _cache_mod

    if (
        _cache_mod._platform_cache
        and time.monotonic() - _cache_mod._platform_cache_ts < COINGECKO_LIST_TTL
    ):
        return _cache_mod._platform_cache
    data = await _get_json(f"{COINGECKO_BASE}/coins/list", params={"include_platform": "true"})
    platforms: dict[str, set[str]] = {}
    if isinstance(data, list):
        for coin in data:
            if not isinstance(coin, dict):
                continue
            coin_id = str(coin.get("id") or "")
            platform_map = coin.get("platforms")
            if not coin_id or not isinstance(platform_map, dict):
                continue
            for platform, address in platform_map.items():
                if address:
                    platforms.setdefault(platform, set()).add(coin_id)
    _cache_mod._platform_cache = platforms
    _cache_mod._platform_cache_ts = time.monotonic()
    return platforms


def _chain_for_coingecko_id(platform_ids: dict[str, set[str]], coin_id: str) -> str:
    """Reverse-map a CoinGecko coin id to a supported chain ("" when unknown)."""
    for chain, platform in COINGECKO_PLATFORMS.items():
        if coin_id in platform_ids.get(platform, set()):
            return chain
    return ""


def _normalize_coingecko_coin(
    coin: dict[str, Any],
    chain: str | None,
    platform_ids: dict[str, set[str]],
) -> dict[str, Any] | None:
    """Normalize a CoinGecko coin (markets / list-new / trending) into the schema."""
    coin_id = str(coin.get("id") or "")
    if not coin_id:
        return None
    if chain is not None:
        platform = COINGECKO_PLATFORMS.get(chain)
        ids = platform_ids.get(platform or "")
        if ids is None or coin_id not in ids:
            return None
    return {
        "chain": chain or _chain_for_coingecko_id(platform_ids, coin_id),
        "address": coin_id,  # CoinGecko id used as pseudo-address (no on-chain addr)
        "symbol": str(coin.get("symbol") or ""),
        "name": str(coin.get("name") or ""),
        "pair_address": "",
        "created_at_utc": _iso(coin.get("activated_at")),
        "price_usd": _f(coin.get("current_price")),
        "liquidity_usd": 0.0,  # not exposed by CoinGecko
        "volume_24h_usd": _f(coin.get("total_volume")),
        "price_change_24h_pct": _f(coin.get("price_change_percentage_24h")),
        "source": "coingecko",
    }


async def _new_tokens_coingecko(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """CoinGecko new-listing fallback (used when DexScreener yields nothing).

    Uses ``/coins/list/new`` when an API key is configured (paid endpoint,
    key read from env only); otherwise falls back to the keyless
    ``/coins/markets`` feed.
    """
    coins: list[dict[str, Any]] = []
    api_key = _api_key("COINGECKO_API_KEY", "PRY_COINGECKO_API_KEY")
    if api_key:
        data = await _get_json(
            f"{COINGECKO_BASE}/coins/list/new",
            headers={"x_cg_pro_api_key": api_key},
        )
        if isinstance(data, list):
            coins = [c for c in data if isinstance(c, dict)]
    if not coins:
        data = await _get_json(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "per_page": 100, "page": 1, "order": "gecko_desc"},
        )
        if isinstance(data, list):
            coins = [c for c in data if isinstance(c, dict)]
    if not coins:
        return []
    platform_ids = await _coingecko_platform_ids()
    results: list[dict[str, Any]] = []
    for coin in coins:
        normalized = _normalize_coingecko_coin(coin, chain, platform_ids)
        if normalized is None:
            continue
        if min_age_minutes > 0:
            age = _entry_age_minutes(normalized)
            if age is None or age < min_age_minutes:
                continue
        results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


async def _trending_coingecko(chain: str | None, limit: int) -> list[dict[str, Any]]:
    """CoinGecko /search/trending + /coins/markets enrichment (fallback)."""
    data = await _get_json(f"{COINGECKO_BASE}/search/trending")
    items: list[dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("coins"), list):
        for entry in data["coins"]:
            if isinstance(entry, dict) and isinstance(entry.get("item"), dict):
                items.append(entry["item"])
    if not items:
        return []
    ids = [str(item.get("id") or "") for item in items if item.get("id")]
    markets: dict[str, dict[str, Any]] = {}
    if ids:
        data = await _get_json(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "ids": ",".join(ids[:COINGECKO_MARKETS_BATCH])},
        )
        if isinstance(data, list):
            markets = {str(m.get("id")): m for m in data if isinstance(m, dict)}
    platform_ids = await _coingecko_platform_ids()
    results: list[dict[str, Any]] = []
    for item in items:
        coin = markets.get(str(item.get("id") or ""), item)
        normalized = _normalize_coingecko_coin(coin, chain, platform_ids)
        if normalized is not None:
            results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


__all__ = [
    "_chain_for_coingecko_id",
    "_coingecko_platform_ids",
    "_new_tokens_coingecko",
    "_normalize_coingecko_coin",
    "_trending_coingecko",
]
