"""DexScreener providers — new tokens, new pairs, and trending tokens.

Primary source for all three public queries: token profiles (newest
launches), token-boosts (trending), and per-token pair lookups for rich
liquidity/volume data. Public endpoints, 60 req/min, no key.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from crypto_market._cache import CACHE_TTL_SECONDS, _cache_get, _cache_set
from crypto_market._http import _get_json
from crypto_market._normalize import (
    _created_epoch,
    _entry_age_minutes,
    _extract_pairs,
    _f,
    _iso,
)
from crypto_market._registry import SUPPORTED_CHAINS

DEXSCREENER_BASE = "https://api.dexscreener.com"
DEXSCREENER_TOKEN_BATCH = 30  # max addresses per tokens/v1 call


async def _dexscreener_profiles() -> list[dict[str, Any]]:
    """Newest token profiles (public, 60 req/min). Cached ~30s."""
    key = "dexscreener:profiles"
    cached = _cache_get(key, CACHE_TTL_SECONDS)
    if cached is not None:
        return cached
    data = await _get_json(f"{DEXSCREENER_BASE}/token-profiles/latest/v1")
    profiles = [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []
    _cache_set(key, profiles)
    return profiles


async def _dexscreener_boosts() -> list[dict[str, Any]]:
    """Latest boosted token entries (public). Cached ~30s."""
    key = "dexscreener:boosts"
    cached = _cache_get(key, CACHE_TTL_SECONDS)
    if cached is not None:
        return cached
    data = await _get_json(f"{DEXSCREENER_BASE}/token-boosts/latest/v1")
    boosts = [b for b in data if isinstance(b, dict)] if isinstance(data, list) else []
    _cache_set(key, boosts)
    return boosts


async def _dexscreener_pairs_for_tokens(chain: str, addresses: list[str]) -> list[dict[str, Any]]:
    """Fetch pairs for token addresses on ``chain`` via tokens/v1 (batch of 30)."""
    if not addresses:
        return []
    key = f"dexscreener:pairs:{chain}:{','.join(addresses)}"
    cached = _cache_get(key, CACHE_TTL_SECONDS)
    if cached is not None:
        return cached
    pairs: list[dict[str, Any]] = []
    for start in range(0, len(addresses), DEXSCREENER_TOKEN_BATCH):
        batch = addresses[start : start + DEXSCREENER_TOKEN_BATCH]
        url = f"{DEXSCREENER_BASE}/tokens/v1/{chain}/{','.join(batch)}"
        data = await _get_json(url)
        pairs.extend(_extract_pairs(data))
    _cache_set(key, pairs)
    return pairs


def _normalize_pair(pair: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Normalize a DexScreener pair dict into the shared schema."""
    base = pair.get("baseToken")
    if not isinstance(base, dict):
        return None
    address = str(base.get("address") or "")
    if not address:
        return None
    chain = str(pair.get("chainId") or "")
    if chain not in SUPPORTED_CHAINS:
        return None
    liquidity = pair.get("liquidity")
    volume = pair.get("volume")
    price_change = pair.get("priceChange")
    return {
        "chain": chain,
        "address": address,
        "symbol": str(base.get("symbol") or ""),
        "name": str(base.get("name") or ""),
        "pair_address": str(pair.get("pairAddress") or ""),
        "created_at_utc": _iso(pair.get("pairCreatedAt")),
        "price_usd": _f(pair.get("priceUsd")),
        "liquidity_usd": _f(liquidity.get("usd")) if isinstance(liquidity, dict) else 0.0,
        "volume_24h_usd": _f(volume.get("h24")) if isinstance(volume, dict) else 0.0,
        "price_change_24h_pct": (
            _f(price_change.get("h24")) if isinstance(price_change, dict) else 0.0
        ),
        "source": source,
    }


def _group_profiles_by_chain(
    profiles: list[dict[str, Any]], chain: str | None
) -> dict[str, list[str]]:
    """Map supported chain -> token addresses, applying the chain filter."""
    grouped: dict[str, list[str]] = {}
    for profile in profiles:
        prof_chain = str(profile.get("chainId") or "")
        if prof_chain not in SUPPORTED_CHAINS:
            continue
        if chain is not None and prof_chain != chain:
            continue
        address = str(profile.get("tokenAddress") or "")
        if address:
            grouped.setdefault(prof_chain, []).append(address)
    return grouped


def _best_pairs_by_token(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the highest-liquidity normalized pair per token address."""
    best_by_token: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        normalized = _normalize_pair(pair, "dexscreener")
        if normalized is None:
            continue
        token_address = str(normalized["address"])
        existing = best_by_token.get(token_address)
        if existing is None or normalized["liquidity_usd"] > existing["liquidity_usd"]:
            best_by_token[token_address] = normalized
    return list(best_by_token.values())


async def _new_tokens_dexscreener(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """New-token detection via DexScreener profiles + per-token pair lookup."""
    profiles = await _dexscreener_profiles()
    if not profiles:
        return []
    grouped = _group_profiles_by_chain(profiles, chain)
    if not grouped:
        return []
    results: list[dict[str, Any]] = []
    for prof_chain, addresses in grouped.items():
        pairs = await _dexscreener_pairs_for_tokens(prof_chain, addresses)
        results.extend(_best_pairs_by_token(pairs))
    if min_age_minutes > 0:
        results = [
            entry
            for entry in results
            if (age := _entry_age_minutes(entry)) is not None and age >= min_age_minutes
        ]
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


async def _new_pairs_dexscreener(chain: str | None, limit: int) -> list[dict[str, Any]]:
    """New-pair detection via DexScreener profiles + all pairs per token."""
    profiles = await _dexscreener_profiles()
    if not profiles:
        return []
    grouped = _group_profiles_by_chain(profiles, chain)
    if not grouped:
        return []
    results: list[dict[str, Any]] = []
    seen_pairs: set[str] = set()
    for prof_chain, addresses in grouped.items():
        pairs = await _dexscreener_pairs_for_tokens(prof_chain, addresses)
        for pair in pairs:
            normalized = _normalize_pair(pair, "dexscreener")
            if normalized is None:
                continue
            pair_address = str(normalized["pair_address"])
            if pair_address and pair_address in seen_pairs:
                continue
            if pair_address:
                seen_pairs.add(pair_address)
            results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


async def _trending_dexscreener(chain: str | None, limit: int) -> list[dict[str, Any]]:
    """Trending tokens from DexScreener token-boosts (primary source)."""
    boosts = await _dexscreener_boosts()
    if not boosts:
        return []
    grouped = _group_profiles_by_chain(boosts, chain)
    if not grouped:
        return []
    results: list[dict[str, Any]] = []
    for boost_chain, addresses in grouped.items():
        pairs = await _dexscreener_pairs_for_tokens(boost_chain, addresses)
        results.extend(_best_pairs_by_token(pairs))
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


__all__ = [
    "_best_pairs_by_token",
    "_dexscreener_boosts",
    "_dexscreener_pairs_for_tokens",
    "_dexscreener_profiles",
    "_group_profiles_by_chain",
    "_new_pairs_dexscreener",
    "_new_tokens_dexscreener",
    "_normalize_pair",
    "_trending_dexscreener",
]
