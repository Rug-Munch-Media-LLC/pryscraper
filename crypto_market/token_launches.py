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

Source notes / honest flags:
  * CoinMarketCap ``/new/`` is a Next.js page scrape: we extract the
    embedded ``__NEXT_DATA__`` JSON (no browser). CMC may block datacenter
    traffic, so this source is best-effort.
  * Birdeye ``/defi/tokenlist`` requires a free API key
    (``PRY_BIRDEYE_API_KEY``) and only exposes per-chain lists; the token
    list carries no creation timestamp, so ``created_at_utc`` uses the
    last-trade time as a recency proxy.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from client import get_client

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=8.0)
CACHE_TTL_SECONDS = 30.0  # in-memory result cache TTL
COINGECKO_LIST_TTL = 3600.0  # /coins/list platform map is big — cache longer
CHAIN_CONTEXT_TTL = 300.0  # DefiLlama chain context TTL
MAX_BACKOFF = 5.0  # cap for rate-limit sleeps (seconds)
RETRY_BASE = 1.0  # base delay for exponential backoff
DEXSCREENER_TOKEN_BATCH = 30  # max addresses per tokens/v1 call
COINGECKO_MARKETS_BATCH = 100  # max ids per /coins/markets call

DEXSCREENER_BASE = "https://api.dexscreener.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEFILLAMA_BASE = "https://api.llama.fi"
CMC_NEW_URL = "https://coinmarketcap.com/new/"
BIRDEYE_TOKENLIST_URL = "https://public-api.birdeye.so/defi/tokenlist"

# Birdeye chain id header values for our supported chains.
BIRDEYE_CHAIN_IDS: dict[str, str] = {
    "ethereum": "ethereum",
    "solana": "solana",
    "base": "base",
    "bsc": "bsc",
    "arbitrum": "arbitrum",
    "polygon": "polygon",
}

SUPPORTED_CHAINS: tuple[str, ...] = (
    "ethereum",
    "solana",
    "base",
    "bsc",
    "arbitrum",
    "polygon",
)

# DexScreener chain id -> CoinGecko platform id (used for chain attribution
# of CoinGecko results via /coins/list?include_platform=true).
COINGECKO_PLATFORMS: dict[str, str] = {
    "ethereum": "ethereum",
    "solana": "solana",
    "base": "base",
    "bsc": "binance-smart-chain",
    "arbitrum": "arbitrum-one",
    "polygon": "polygon-pos",
}

# ── In-memory caches ────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_platform_cache: dict[str, set[str]] = {}
_platform_cache_ts: float = 0.0


def _cache_get(key: str, ttl: float) -> list[dict[str, Any]] | None:
    """Return a shallow copy of a cached list, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > ttl:
        _cache.pop(key, None)
        return None
    return [dict(item) for item in value]


def _cache_set(key: str, value: list[dict[str, Any]]) -> None:
    """Store a shallow copy of a list under ``key``."""
    _cache[key] = (time.monotonic(), [dict(item) for item in value])


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    global _platform_cache_ts
    _cache.clear()
    _platform_cache.clear()
    _platform_cache_ts = 0.0


# ── Small helpers ──────────────────────────────────────────────────────
def _normalize_chain_arg(chain: str | None) -> str | None:
    """Normalize the ``chain`` argument; None/""/"all" mean no filtering."""
    if chain is None:
        return None
    normalized = str(chain).strip().lower()
    if normalized in ("", "all"):
        return None
    return normalized


def _epoch_ms(value: Any) -> float | None:
    """Coerce a timestamp to epoch milliseconds.

    Handles both millisecond (DexScreener ``pairCreatedAt``) and second
    (CoinGecko ``activated_at``) inputs.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number if number > 1e12 else number * 1000.0


def _iso(value: Any) -> str:
    """ISO-8601 UTC string from an epoch timestamp (ms or s); "" on failure."""
    ms = _epoch_ms(value)
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a numeric value to float; ``default`` on any failure."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _created_epoch(entry: dict[str, Any]) -> float:
    """Wall-clock epoch seconds of a normalized entry; -1 when unknown."""
    raw = entry.get("created_at_utc")
    if not raw:
        return -1.0
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except (ValueError, TypeError, OSError):
        return -1.0


def _entry_age_minutes(entry: dict[str, Any]) -> float | None:
    """Age of an entry in minutes; None when creation time is unknown."""
    epoch = _created_epoch(entry)
    if epoch <= 0:
        return None
    return max(0.0, (time.time() - epoch) / 60.0)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse the Retry-After header (seconds) if present."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


# ── HTML / embedded-JSON helpers (CoinMarketCap scrape) ────────────────
_NEXT_DATA_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _extract_next_data(html_text: str) -> dict[str, Any] | None:
    """Pull and parse the ``__NEXT_DATA__`` JSON blob from a Next.js page."""
    match = _NEXT_DATA_RE.search(html_text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cmc_chain_from_platform(platform: Any) -> str:
    """Map a CoinMarketCap platform id/name to a supported chain ("" unknown)."""
    platform_id = ""
    if isinstance(platform, dict):
        platform_id = str(platform.get("id") or platform.get("name") or "")
    elif platform is not None:
        platform_id = str(platform)
    pid = platform_id.strip().lower()
    aliases = {
        "ethereum": "ethereum",
        "solana": "solana",
        "base": "base",
        "bnb": "bsc",
        "binance-smart-chain": "bsc",
        "arbitrum": "arbitrum",
        "arbitrum-one": "arbitrum",
        "polygon-pos": "polygon",
        "polygon": "polygon",
    }
    return aliases.get(pid, "")


def _extract_cmc_coin_rows(node: Any, out: list[dict[str, Any]]) -> None:
    """Recursively collect CoinMarketCap coin-row dicts from the page state.

    CMC's new-listings page stores rows under ``props.initialState...data``
    with per-coin ``quote.USD``; walk the whole embedded JSON for dicts that
    look like coin rows (have ``symbol`` + ``quote.USD``).
    """
    if isinstance(node, list):
        for child in node:
            _extract_cmc_coin_rows(child, out)
        return
    if not isinstance(node, dict):
        return
    quote = node.get("quote")
    if (
        isinstance(quote, dict)
        and isinstance(quote.get("USD"), dict)
        and str(node.get("symbol") or "").strip()
        and str(node.get("name") or "").strip()
    ):
        out.append(node)
    for value in node.values():
        _extract_cmc_coin_rows(value, out)


def _normalize_cmc_row(row: dict[str, Any], chain_filter: str | None) -> dict[str, Any] | None:
    """Normalize a CoinMarketCap coin row into the shared schema.

    ``chain`` is attributed from the platform field when possible; rows with
    an unknown chain are kept only when no chain filter is applied (their
    ``chain`` is left empty per the schema).
    """
    quote = row.get("quote")
    usd = quote.get("USD") if isinstance(quote, dict) else None
    if not isinstance(usd, dict):
        return None
    symbol = str(row.get("symbol") or "")
    name = str(row.get("name") or "")
    if not symbol and not name:
        return None
    chain = _cmc_chain_from_platform(row.get("platform"))
    if chain_filter is not None and chain != chain_filter:
        return None
    return {
        "chain": chain,
        "address": str(row.get("tokenAddress") or row.get("slug") or ""),
        "symbol": symbol,
        "name": name,
        "pair_address": "",
        "created_at_utc": _normalize_iso_utc(row.get("date_added") or row.get("last_updated")),
        "price_usd": _f(usd.get("price")),
        "liquidity_usd": 0.0,  # not exposed by the CMC scrape
        "volume_24h_usd": _f(usd.get("volume_24h")),
        "price_change_24h_pct": _f(usd.get("percent_change_24h")),
        "source": "coinmarketcap",
    }


def _normalize_iso_utc(value: Any) -> str:
    """Normalize an ISO-8601 string to ISO-8601 UTC ("" on failure)."""
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _extract_pairs(data: Any) -> list[dict[str, Any]]:
    """Extract a pair list from a DexScreener response.

    Handles both shapes the API returns: ``{"pairs": [...]}`` and a bare
    list, plus null pairs (search returns ``pairs: null`` on no results).
    """
    if isinstance(data, dict):
        pairs = data.get("pairs")
        if isinstance(pairs, list):
            return [p for p in pairs if isinstance(p, dict)]
        return []
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    return []


def _api_key(*names: str) -> str:
    """Read an optional API key from the environment (never hardcoded)."""
    for name in names:
        value = os.getenv(name, "")
        if value:
            return value
    return ""


# ── HTTP with timeout + backoff ────────────────────────────────────────
async def _get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 2,
) -> Any:
    """GET ``url`` and return parsed JSON; None on any failure.

    Retries with exponential backoff on 429 (honoring Retry-After), 5xx,
    and transport errors. All failure modes return None so callers never
    see an exception.
    """
    client = await get_client()
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code == 429:
                retry_after = _retry_after_seconds(resp)
                delay = retry_after if retry_after is not None else RETRY_BASE * (2**attempt)
                await asyncio.sleep(min(delay, MAX_BACKOFF))
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))
                continue
            if not resp.is_success:
                return None
            return resp.json()
        except httpx.HTTPError as exc:  # transport errors, timeouts, 4xx-as-error
            logger.warning(
                "crypto_market_http_error",
                extra={"url": url[:120], "error": str(exc)[:120], "attempt": attempt},
            )
            await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "crypto_market_bad_json",
                extra={"url": url[:120], "error": str(exc)[:120]},
            )
            return None
    return None


# ── DexScreener providers ──────────────────────────────────────────────
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
        best_by_token: dict[str, dict[str, Any]] = {}
        for pair in pairs:
            normalized = _normalize_pair(pair, "dexscreener")
            if normalized is None:
                continue
            token_address = str(normalized["address"])
            existing = best_by_token.get(token_address)
            if existing is None or normalized["liquidity_usd"] > existing["liquidity_usd"]:
                best_by_token[token_address] = normalized
        results.extend(best_by_token.values())
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
        best_by_token: dict[str, dict[str, Any]] = {}
        for pair in pairs:
            normalized = _normalize_pair(pair, "dexscreener")
            if normalized is None:
                continue
            token_address = str(normalized["address"])
            existing = best_by_token.get(token_address)
            if existing is None or normalized["liquidity_usd"] > existing["liquidity_usd"]:
                best_by_token[token_address] = normalized
        results.extend(best_by_token.values())
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


# ── CoinGecko providers ────────────────────────────────────────────────
async def _coingecko_platform_ids() -> dict[str, set[str]]:
    """Map CoinGecko platform -> set of coin ids (/coins/list, cached 1h)."""
    global _platform_cache, _platform_cache_ts
    if _platform_cache and time.monotonic() - _platform_cache_ts < COINGECKO_LIST_TTL:
        return _platform_cache
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
    _platform_cache = platforms
    _platform_cache_ts = time.monotonic()
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


# ── CoinMarketCap new-listings scrape ─────────────────────────────────
async def _get_text(url: str, *, params: dict[str, Any] | None = None) -> str:
    """GET ``url`` and return the response text; "" on any failure."""
    client = await get_client()
    try:
        resp = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        logger.warning(
            "crypto_market_http_text_error",
            extra={"url": url[:120], "error": str(exc)[:120]},
        )
        return ""


async def _new_tokens_cmc(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """CoinMarketCap new-listings page scrape (best-effort, no key).

    Parses the embedded ``__NEXT_DATA__`` JSON from ``coinmarketcap.com/new/``.
    CMC can block datacenter traffic; any failure degrades to ``[]``.
    """
    page = await _get_text(CMC_NEW_URL)
    if not page:
        return []
    payload = _extract_next_data(page)
    if payload is None:
        return []
    rows: list[dict[str, Any]] = []
    _extract_cmc_coin_rows(payload, rows)
    if not rows:
        return []
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_cmc_row(row, chain)
        if normalized is None:
            continue
        dedupe_key = f"{normalized['symbol']}:{normalized['name']}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if min_age_minutes > 0:
            age = _entry_age_minutes(normalized)
            if age is None or age < min_age_minutes:
                continue
        results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


# ── Birdeye token list ────────────────────────────────────────────────
def _normalize_birdeye_token(token: dict[str, Any], chain: str) -> dict[str, Any] | None:
    """Normalize a Birdeye ``/defi/tokenlist`` token into the shared schema.

    The token list exposes market data (``mc``, ``v24hUSD``,
    ``v24hChangePercent``, ``liquidity``, ``lastTradeUnixTime``) but no
    live price or creation time — ``price_usd`` defaults to 0.0 and
    ``created_at_utc`` is a last-trade recency proxy.
    """
    address = str(token.get("address") or "")
    symbol = str(token.get("symbol") or "")
    name = str(token.get("name") or "")
    if not address or (not symbol and not name):
        return None
    return {
        "chain": chain,
        "address": address,
        "symbol": symbol,
        "name": name,
        "pair_address": "",
        "created_at_utc": _iso(token.get("lastTradeUnixTime")),
        "price_usd": 0.0,  # tokenlist has no live price
        "liquidity_usd": _f(token.get("liquidity")),
        "volume_24h_usd": _f(token.get("v24hUSD")),
        "price_change_24h_pct": _f(token.get("v24hChangePercent")),
        "source": "birdeye",
    }


async def _birdeye_tokens_for_chain(chain: str) -> list[dict[str, Any]]:
    """Fetch one Birdeye token list page for ``chain`` (needs a free key)."""
    api_key = _api_key("PRY_BIRDEYE_API_KEY", "BIRDEYE_API_KEY")
    if not api_key:
        logger.info("crypto_market_birdeye_skipped_no_api_key")
        return []
    chain_id = BIRDEYE_CHAIN_IDS.get(chain)
    if not chain_id:
        return []
    data = await _get_json(
        BIRDEYE_TOKENLIST_URL,
        params={"limit": 50, "offset": 0, "sort_by": "v24hUSD", "sort_type": "desc"},
        headers={"X-API-KEY": api_key, "x-chain": chain_id},
    )
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    tokens = inner.get("tokens") if isinstance(inner, dict) else None
    if not isinstance(tokens, list):
        return []
    results: list[dict[str, Any]] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        normalized = _normalize_birdeye_token(token, chain)
        if normalized is not None:
            results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results


async def _new_tokens_birdeye(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """Birdeye token-list fallback (needs a free ``PRY_BIRDEYE_API_KEY``).

    Honest flags: no creation timestamp (recency is last-trade based) and no
    live price. ``min_age_minutes`` therefore filters on the recency proxy.
    """
    chains = [chain] if chain is not None else list(SUPPORTED_CHAINS)
    results: list[dict[str, Any]] = []
    for name in chains:
        results.extend(await _birdeye_tokens_for_chain(name))
    if min_age_minutes > 0:
        results = [
            entry
            for entry in results
            if (age := _entry_age_minutes(entry)) is not None and age >= min_age_minutes
        ]
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


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
