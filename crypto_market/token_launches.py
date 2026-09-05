"""Crypto token-launch detection built on free public APIs.

Detects newly launched tokens / pairs and trending tokens using only
keyless free-tier providers (DexScreener, CoinGecko, DefiLlama) plus two
best-effort secondary sources (CoinMarketCap new-listings scrape and the
Birdeye token list). Optional API keys (e.g. ``COINGECKO_API_KEY`` /
``PRY_COINGECKO_API_KEY`` / ``PRY_BIRDEYE_API_KEY``) are read from the
environment when present — never hardcoded — and unlock paid endpoints
such as ``/coins/list/new`` or the Birdeye ``/defi/tokenlist`` without
changing the public contract.

Contract (used by the MCP / x402 wiring):

* ``get_new_tokens(chain, limit, min_age_minutes)`` — newest tokens.
* ``get_new_pairs(chain, limit)`` — newest liquidity pairs.
* ``get_trending_tokens(chain, limit)`` — trending tokens.

Every returned item is normalized to:

    {
        "chain": str,                 # one of SUPPORTED_CHAINS ("" if unknown)
        "address": str,               # base token address / CoinGecko id
        "symbol": str,
        "name": str,
        "pair_address": str,          # "" when the source has no pair concept
        "created_at_utc": str,        # ISO-8601 UTC, "" when unknown
        "price_usd": float,
        "liquidity_usd": float,
        "volume_24h_usd": float,
        "price_change_24h_pct": float,
        "source": str,                # "dexscreener" | "coingecko" | "coinmarketcap" | "birdeye"
    }

Robustness guarantees:
  * never raises — every provider failure yields an empty list
  * per-request timeouts on the shared httpx client
  * exponential backoff with Retry-After support on 429 / 5xx / transport
    errors
  * in-memory result cache (~30s) to avoid hammering free tiers

Implementation is split across cohesive sibling modules (all private,
``_``-prefixed): ``_registry`` (static data, loaded from ``_registry.json``),
``_cache``, ``_http``, ``_normalize``, and one provider module per source
(``_dexscreener``, ``_coingecko``, ``_cmc``, ``_birdeye``). This module
owns the public API and the fallback orchestration.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

import crypto_market._http as _http  # noqa: F401 — re-exported for test patching
from crypto_market._birdeye import _new_tokens_birdeye
from crypto_market._cache import (
    CACHE_TTL_SECONDS,
    CHAIN_CONTEXT_TTL,
    _cache_get,
    _cache_set,
    _clear_cache,
)
from crypto_market._cmc import _new_tokens_cmc
from crypto_market._coingecko import _new_tokens_coingecko, _trending_coingecko
from crypto_market._dexscreener import (
    _new_pairs_dexscreener,
    _new_tokens_dexscreener,
    _trending_dexscreener,
)
from crypto_market._http import _get_json
from crypto_market._normalize import _f, _normalize_chain_arg
from crypto_market._registry import SUPPORTED_CHAINS

logger = logging.getLogger(__name__)

DEFILLAMA_BASE = "https://api.llama.fi"

__all__ = [
    "SUPPORTED_CHAINS",
    "_clear_cache",
    "get_chain_context",
    "get_new_pairs",
    "get_new_tokens",
    "get_trending_tokens",
]


# ── DefiLlama chain context ────────────────────────────────────────────
async def get_chain_context(chain: str = "all") -> list[dict[str, Any]]:
    """Chain context from DefiLlama (TVL snapshot per chain, free, cached 5m).

    Each entry: ``{"chain": <our chain id or llama name>, "name": ..., "tvl_usd": float}``.
    Empty list on failure — never raises.
    """
    try:
        normalized = _normalize_chain_arg(chain)
        key = f"defillama:chains:{normalized or 'all'}"
        cached = _cache_get(key, CHAIN_CONTEXT_TTL)
        if cached is not None:
            return cached
        data = await _get_json(f"{DEFILLAMA_BASE}/v2/chains")
        if not isinstance(data, list):
            return []
        results: list[dict[str, Any]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            chain_id = str(entry.get("chainId") or "")
            if not name and not chain_id:
                continue
            if normalized is not None and normalized not in (name.lower(), chain_id.lower()):
                continue
            results.append(
                {
                    "chain": chain_id if chain_id else name.lower(),
                    "name": name,
                    "tvl_usd": _f(entry.get("tvl")),
                }
            )
        results.sort(key=lambda item: item["tvl_usd"], reverse=True)
        _cache_set(key, results)
        return results
    except Exception:  # noqa: BLE001 — public API boundary: never-raise contract
        logger.warning("crypto_market_chain_context_failed", exc_info=False)
        return []


# ── Public API ─────────────────────────────────────────────────────────
async def get_new_tokens(
    chain: str = "all", limit: int = 50, min_age_minutes: int = 0
) -> list[dict[str, Any]]:
    """Return the newest launched tokens, normalized into the shared schema.

    Sources are tried in fallback order: DexScreener (token profiles +
    per-token pairs) → CoinGecko new listings → CoinMarketCap new-listings
    scrape → Birdeye token list. When a source yields nothing the next one
    is consulted, so one provider being down never empties the result.
    ``min_age_minutes`` filters to tokens that are at least that many
    minutes old (0 disables the filter). Never raises.
    """
    try:
        normalized = _normalize_chain_arg(chain)
        if normalized is not None and normalized not in SUPPORTED_CHAINS:
            return []
        count = max(0, int(limit))
        min_age = max(0, int(min_age_minutes))
        cache_key = f"new_tokens:{normalized or 'all'}:{count}:{min_age}"
        cached = _cache_get(cache_key, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        result = await _new_tokens_dexscreener(normalized, count, min_age)
        if not result:
            result = await _new_tokens_coingecko(normalized, count, min_age)
        if not result:
            result = await _new_tokens_cmc(normalized, count, min_age)
        if not result:
            result = await _new_tokens_birdeye(normalized, count, min_age)
        _cache_set(cache_key, result)
        return result
    except Exception:  # noqa: BLE001 — public API boundary: never-raise contract
        logger.warning("crypto_market_get_new_tokens_failed", exc_info=False)
        return []


async def get_new_pairs(chain: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    """Return the newest liquidity pairs (DexScreener), newest first.

    Every pair for recently profiled tokens is collected and sorted by pool
    creation time, deduplicated by pair address. Never raises.
    """
    try:
        normalized = _normalize_chain_arg(chain)
        if normalized is not None and normalized not in SUPPORTED_CHAINS:
            return []
        count = max(0, int(limit))
        cache_key = f"new_pairs:{normalized or 'all'}:{count}"
        cached = _cache_get(cache_key, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        result = await _new_pairs_dexscreener(normalized, count)
        _cache_set(cache_key, result)
        return result
    except Exception:  # noqa: BLE001 — public API boundary: never-raise contract
        logger.warning("crypto_market_get_new_pairs_failed", exc_info=False)
        return []


async def get_trending_tokens(chain: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Return trending tokens, normalized into the shared schema.

    Primary source is DexScreener token-boosts (chain-attributed, rich
    pair data); falls back to CoinGecko ``/search/trending`` enriched with
    ``/coins/markets``. Never raises.
    """
    try:
        normalized = _normalize_chain_arg(chain)
        if normalized is not None and normalized not in SUPPORTED_CHAINS:
            return []
        count = max(0, int(limit))
        cache_key = f"trending:{normalized or 'all'}:{count}"
        cached = _cache_get(cache_key, CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        result = await _trending_dexscreener(normalized, count)
        if not result:
            result = await _trending_coingecko(normalized, count)
        _cache_set(cache_key, result)
        return result
    except Exception:  # noqa: BLE001 — public API boundary: never-raise contract
        logger.warning("crypto_market_get_trending_tokens_failed", exc_info=False)
        return []
