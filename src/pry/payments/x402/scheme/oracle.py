"""Pry — x402 USD price oracle (live providers + static fallback, cached)."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .enums import _STABLECOIN_ASSETS

logger = logging.getLogger(__name__)

# USD value of ONE unit of each asset, used to quote USD-equivalent atomic
# amounts for non-1:1 assets (ETH/ARB/SOL/TRX/POL/…). Stablecoins are fixed
# at 1.0. Volatile assets use env-overridable STATIC defaults as the
# fallback; the live-oracle hook ``get_asset_usd_price`` quotes them from a
# free price oracle (CoinGecko ``/simple/price`` when
# ``PRY_X402_ORACLE_SOURCE=coingecko``) with an async cache + TTL, falling
# back to these static values with ``usdPerUnitSource:"static-default"`` only
# when the oracle is unreachable.
X402_ASSET_USD_PER_UNIT: dict[str, float] = {
    "USDC": 1.0,
    "USDT": 1.0,
    "DAI": 1.0,
    "ETH": float(os.getenv("PRY_X402_USD_PER_UNIT_ETH", "2500")),
    "WETH": float(os.getenv("PRY_X402_USD_PER_UNIT_WETH", "2500")),
    "ARB": float(os.getenv("PRY_X402_USD_PER_UNIT_ARB", "0.6")),
    "SOL": float(os.getenv("PRY_X402_USD_PER_UNIT_SOL", "140")),
    "MATIC": float(os.getenv("PRY_X402_USD_PER_UNIT_MATIC", "0.4")),
    "POL": float(os.getenv("PRY_X402_USD_PER_UNIT_POL", "0.4")),
    "TRX": float(os.getenv("PRY_X402_USD_PER_UNIT_TRX", "0.15")),
}

# Live price oracle. The fetcher is REAL and wired: with a provider
# configured it hits CoinGecko's free ``/simple/price`` (no API key) or a
# custom JSON endpoint and caches with TTL, falling back to the static table
# only on failure. The provider is opt-in (``PRY_X402_ORACLE_SOURCE``) so the
# existing default contract — static ``usdPerUnitSource:"static-default"``
# prices unless an operator configures a live source — is preserved.
# Re-read from env per call so tests can toggle providers without reloading
# the module.
X402_ORACLE_URL: str = os.getenv("PRY_X402_ORACLE_URL", "")
X402_ORACLE_SOURCE: str = os.getenv("PRY_X402_ORACLE_SOURCE", "")
X402_ORACLE_TTL_SECONDS: float = float(os.getenv("PRY_X402_ORACLE_TTL", "60"))

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# Asset symbol -> CoinGecko coin id for /simple/price lookups. WETH tracks
# ETH; MATIC maps to the legacy id (POL is the polygon ecosystem token).
COINGECKO_ASSET_IDS: dict[str, str] = {
    "ETH": "ethereum",
    "WETH": "ethereum",
    "ARB": "arbitrum",
    "SOL": "solana",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "TRX": "tron",
    "BTC": "bitcoin",
    "LTC": "litecoin",
    "DOGE": "dogecoin",
}

# Async price cache: (source_key, asset, network) -> (monotonic_ts, usd).
# Keying by source means a test/operator toggling providers can never read a
# stale quote from a different provider.
_oracle_cache: dict[tuple[str, str, str], tuple[float, float]] = {}


def clear_price_cache() -> None:  # test-only
    """Drop all cached oracle quotes (tests, provider toggles, re-probe)."""
    _oracle_cache.clear()


def oracle_source_label() -> str:
    """Return the active oracle provider label.

    ``"custom"`` (``PRY_X402_ORACLE_URL``), ``"coingecko"`` /
    ``"dexscreener"`` (``PRY_X402_ORACLE_SOURCE``), or ``"static-default"``
    when no live provider is configured.
    """
    if os.getenv("PRY_X402_ORACLE_URL") or X402_ORACLE_URL:
        return "custom"
    source = os.getenv("PRY_X402_ORACLE_SOURCE", X402_ORACLE_SOURCE)
    if source in ("coingecko", "dexscreener"):
        return source
    return "static-default"


@dataclass(frozen=True)
class AssetUsdQuote:
    """USD price of one unit of an asset plus where it came from.

    ``source`` is ``"oracle"`` (live), ``"stablecoin"`` (fixed 1:1) or
    ``"static-default"`` (fallback static table).
    """

    usd: float
    source: str


def _extract_usd_from_json(data: Any, coingecko_id: str = "") -> float | None:
    """Pull a positive USD price out of an oracle response.

    Handles the custom endpoint shapes (``{"usd": ...}``, ``{"data":
    {"usd": ...}}``) and the CoinGecko shape (``{id: {"usd": ...}}``).
    """
    if not isinstance(data, dict):
        return None
    if coingecko_id and isinstance(data.get(coingecko_id), dict):
        value = data[coingecko_id].get("usd")
        if isinstance(value, (int, float)) and float(value) > 0:
            return float(value)
    for candidate in (data, data.get("data") if isinstance(data, dict) else None):
        if not isinstance(candidate, dict):
            continue
        for key in ("usd", "priceUsd", "price"):
            value = candidate.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
    return None


async def _fetch_oracle_price(asset: str, network: str = "") -> float | None:
    """Fetch a live USD price from the configured oracle; None on any failure.

    Provider resolution order:
    1. ``PRY_X402_ORACLE_URL`` set → ``GET {url}/price/{ASSET}`` (custom
       endpoint, backward compatible with the pre-production hook);
    2. ``PRY_X402_ORACLE_SOURCE`` set to ``coingecko`` → CoinGecko
       ``/simple/price?ids={id}&vs_currencies=usd``;
    3. otherwise None — no live provider configured (static defaults).
    """
    oracle_url = os.getenv("PRY_X402_ORACLE_URL") or X402_ORACLE_URL
    asset = asset.upper()
    if oracle_url:
        url = f"{oracle_url.rstrip('/')}/price/{asset}"
        if network:
            url += f"?network={network}"
    else:
        source = os.getenv("PRY_X402_ORACLE_SOURCE", X402_ORACLE_SOURCE)
        if source not in ("coingecko", "dexscreener"):
            return None
        coingecko_id = COINGECKO_ASSET_IDS.get(asset)
        if not coingecko_id:
            return None
        url = f"{COINGECKO_SIMPLE_PRICE_URL}?ids={coingecko_id}&vs_currencies=usd"
    try:
        timeout = float(os.getenv("PRY_X402_ORACLE_TIMEOUT", "5"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError, OSError):
        logger.warning(
            "x402_oracle_unavailable_falling_back",
            extra={"asset": asset, "oracle_url": oracle_url or oracle_source_label()},
        )
        return None
    coingecko_id = COINGECKO_ASSET_IDS.get(asset) if not oracle_url else ""
    return _extract_usd_from_json(data, coingecko_id or "")


async def get_asset_usd_price(asset: str, network: str = "") -> AssetUsdQuote:
    """Live-oracle hook: USD price of one unit of ``asset``.

    Stablecoins (USDC/USDT/DAI) are fixed 1:1 and never hit the network.
    Volatile assets are quoted from the live oracle with an async cache + TTL
    (``PRY_X402_ORACLE_TTL``, default 60s — at most one call per asset per
    TTL). Any failure falls back to the static ``X402_ASSET_USD_PER_UNIT``
    table, reporting ``source="static-default"`` (stablecoins report
    ``"stablecoin"``).

    This is the canonical quote path for async verification
    (``SelfFacilitator.verify``); the sync pricing helpers
    (``usd_per_unit_for`` / ``asset_to_atomic`` / ``build_multi_asset_accepts``)
    keep using the static table so accept-list construction stays sync.
    """
    asset = asset.upper()
    if asset in _STABLECOIN_ASSETS:
        static = X402_ASSET_USD_PER_UNIT.get(asset)
        return AssetUsdQuote(usd=static if static and static > 0 else 1.0, source="stablecoin")
    source_key = oracle_source_label()
    if source_key == "static-default":
        # No live provider configured — the existing default contract is
        # static prices (no network traffic, no rate-limit exposure).
        static = X402_ASSET_USD_PER_UNIT.get(asset)
        return AssetUsdQuote(usd=static if static and static > 0 else 1.0, source="static-default")
    cache_key = (source_key, asset, network)
    now = time.monotonic()
    ttl = float(os.getenv("PRY_X402_ORACLE_TTL", str(X402_ORACLE_TTL_SECONDS)))
    entry = _oracle_cache.get(cache_key)
    if entry is not None and now - entry[0] < ttl:
        return AssetUsdQuote(usd=entry[1], source="oracle")
    live = await _fetch_oracle_price(asset, network)
    if live is not None:
        _oracle_cache[cache_key] = (now, live)
        return AssetUsdQuote(usd=live, source="oracle")
    static = X402_ASSET_USD_PER_UNIT.get(asset)
    if static is None or static <= 0:
        static = 1.0
    return AssetUsdQuote(usd=static, source="static-default")


async def probe_oracle() -> tuple[bool, str]:
    """Probe the configured price oracle with a single live call.

    Returns ``(reachable, source)``. ``reachable`` is True only when a live
    (``"oracle"``-sourced) quote was obtained; ``source`` is the provider
    label from :func:`oracle_source_label` (``"static-default"`` when no live
    provider is configured). Used by ``/v1/x402/health``.
    """
    # Resolved through the scheme package at call time so tests patching
    # ``pry.payments.x402.scheme.get_asset_usd_price`` keep working.
    import pry.payments.x402.scheme as pkg

    asset = os.getenv("PRY_X402_ORACLE_PROBE_ASSET", "ETH")
    quote = await pkg.get_asset_usd_price(asset)
    return quote.source == "oracle", oracle_source_label()
