"""Pry — x402 scheme/offer/pricing helpers.

Owns the x402 enums, the server-side pricing table, atomic-unit conversion,
Base64 header codecs, network/asset compatibility mapping, the
spec-compliant ``build_payment_required`` builder, and the legacy (pre-spec)
payment-request helpers. Config constants (``X402_WALLET``,
``X402_DEFAULT_ASSET``, …) are imported from the package root.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

import httpx

from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_NETWORK_WALLETS,
    X402_PLACEHOLDER_WALLETS,
    X402_WALLET,
    is_evm_address,
    is_solana_address,
    is_tron_address,
)

# Attestation crypto: same backend the self-facilitator uses (eth_keys for
# secp256k1 ecrecover/sign, eth_utils keccak for the digest). Imported
# best-effort so the module still loads (and attestation is simply disabled)
# if the crypto deps are unavailable in a stripped runtime. Resolved lazily —
# a mock/reload never has to re-import.
try:  # pragma: no cover - depends on runtime deps
    from eth_keys import keys as _eth_keys
    from eth_utils import keccak as _keccak
except Exception:  # noqa: BLE001 - optional crypto dep; attestation disabled
    # (backward compatible) even when eth_keys/eth_utils are absent.
    _eth_keys = None
    _keccak = None
    logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# x402 pricing per operation (USDC atomic units, 6 decimals).
#
# Each entry may optionally carry a ``prices`` sub-table keyed by CAIP-2
# network id -> asset -> USD price, allowing per-network per-asset prices to
# override the base ``price_usd`` (see ``resolve_price_usd``). Example:
#   "scrape": {
#       "price_usd": 0.001,
#       "description": "Single URL scrape",
#       "prices": {"eip155:137": {"USDC": 0.0008}},  # cheaper on Polygon
#   }
X402_PRICING: dict[str, dict[str, Any]] = {
    "scrape": {"price_usd": 0.001, "description": "Single URL scrape"},
    "crawl": {"price_usd": 0.01, "description": "Crawl up to 10 pages"},
    "extract": {"price_usd": 0.005, "description": "Structured extraction"},
    "monitor": {"price_usd": 0.02, "description": "Create scheduled monitor"},
    "llm_call": {"price_usd": 0.01, "description": "LLM extraction call"},
    "template_execute": {"price_usd": 0.002, "description": "Execute scraper template"},
    "template_batch_execute": {"price_usd": 0.01, "description": "Execute up to 20 template items"},
    "browser_automation": {"price_usd": 0.05, "description": "Browser automation"},
    "bulk_crawl": {"price_usd": 0.10, "description": "Crawl up to 1000 pages"},
    "pdf_extract": {"price_usd": 0.01, "description": "PDF table extraction"},
    "ocr_extract": {"price_usd": 0.005, "description": "Image OCR"},
    "graphql_query": {"price_usd": 0.003, "description": "GraphQL query execution"},
    "schema_extract": {"price_usd": 0.002, "description": "Schema.org/JSON-LD extraction"},
}


class X402Scheme(StrEnum):
    """Payment schemes supported by x402."""

    EXACT = "exact"
    UPTO = "upto"


class X402Network(StrEnum):
    """Blockchain networks supported by x402."""

    BASE = "base"
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BNB = "bnb"
    AVALANCHE = "avalanche"
    BASE_SEPOLIA = "base-sepolia"
    TRON = "tron"
    BITCOIN = "bitcoin"
    LITECOIN = "litecoin"
    DOGECOIN = "dogecoin"


class X402Asset(StrEnum):
    """Token assets supported by x402."""

    USDC = "USDC"
    USDT = "USDT"
    DAI = "DAI"
    ETH = "ETH"
    WETH = "WETH"
    ARB = "ARB"
    SOL = "SOL"
    MATIC = "MATIC"
    POL = "POL"
    TRX = "TRX"
    BTC = "BTC"
    LTC = "LTC"
    DOGE = "DOGE"


# Native assets that settle via plain value transfers on the EIP-7702 RPCs.
_NATIVE_ASSETS = {X402Asset.ETH.value}

# Asset decimals for atomic conversion
ASSET_DECIMALS: dict[str, int] = {
    X402Asset.USDC.value: 6,
    X402Asset.USDT.value: 6,
    X402Asset.DAI.value: 18,
    X402Asset.ETH.value: 18,
    X402Asset.WETH.value: 18,
    X402Asset.ARB.value: 18,
    X402Asset.SOL.value: 9,
    X402Asset.MATIC.value: 18,
    X402Asset.POL.value: 18,
    X402Asset.TRX.value: 6,
    X402Asset.BTC.value: 8,
    X402Asset.LTC.value: 8,
    X402Asset.DOGE.value: 8,
}

# ── Canonical multi-chain / multi-asset acceptance table ────────────────────
#
# SUPPORTED_ASSETS is the single source of truth for which (network, asset)
# pairs Pry accepts for x402 payments, keyed by CAIP-2 network id + asset
# symbol. `verification` names the authorization method:
#
#   eip3009 — ERC-20 transferWithAuthorization (USDC)
#   permit2 — ERC-20 Permit2 (USDT / ARB / WETH / …)
#   native  — plain value transfer of the chain's native asset
#   spl     — Solana SPL token transfer
#   trc20   — TRON TRC-20 transfer
#
# `kind` distinguishes contract tokens from native assets (contract == ""
# for native). Contract addresses are well-known mainnet addresses.

# CAIP-2 network ids. Legacy x402 network names (X402Network enum values) map
# to these; both spellings are accepted everywhere.
CAIP2_NETWORK_IDS: dict[str, str] = {
    "base": "eip155:8453",
    "ethereum": "eip155:1",
    "arbitrum": "eip155:42161",
    "optimism": "eip155:10",
    "polygon": "eip155:137",
    "solana": "solana:mainnet",
    "tron": "tron:mainnet",
}

SUPPORTED_NETWORKS: list[dict[str, Any]] = [
    {"network": "eip155:8453", "name": "Base", "family": "evm", "chain": "eip155"},
    {"network": "eip155:1", "name": "Ethereum", "family": "evm", "chain": "eip155"},
    {"network": "eip155:42161", "name": "Arbitrum", "family": "evm", "chain": "eip155"},
    {"network": "eip155:10", "name": "Optimism", "family": "evm", "chain": "eip155"},
    {"network": "eip155:137", "name": "Polygon", "family": "evm", "chain": "eip155"},
    {"network": "solana:mainnet", "name": "Solana", "family": "solana", "chain": "solana"},
    {"network": "tron:mainnet", "name": "TRON", "family": "tron", "chain": "tron"},
]

SUPPORTED_ASSETS: dict[str, dict[str, dict[str, Any]]] = {
    "eip155:8453": {
        "USDC": {
            "asset": "USDC",
            "network": "eip155:8453",
            "name": "Base USDC",
            "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6,
            "verification": "eip3009",
            "kind": "erc20",
        },
        "USDT": {
            "asset": "USDT",
            "network": "eip155:8453",
            "name": "Base USDT",
            # Canonical bridged Tether USD on Base. This is the SINGLE source
            # of truth: the legacy V1 EIP7702_TOKEN_ADDRESSES table derives
            # its Base USDT entry from here (x402/__init__.py). The address it
            # previously hardcoded (0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb)
            # is DAI on Base, not USDT.
            "contract": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",
            "decimals": 6,
            "verification": "permit2",
            "kind": "erc20",
        },
        "ETH": {
            "asset": "ETH",
            "network": "eip155:8453",
            "name": "Base ETH",
            "contract": "",
            "decimals": 18,
            "verification": "native",
            "kind": "native",
        },
        "WETH": {
            "asset": "WETH",
            "network": "eip155:8453",
            "name": "Base WETH",
            "contract": "0x4200000000000000000000000000000000000006",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
    },
    "eip155:1": {
        "USDC": {
            "asset": "USDC",
            "network": "eip155:1",
            "name": "Ethereum USDC",
            "contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "decimals": 6,
            "verification": "eip3009",
            "kind": "erc20",
        },
        "USDT": {
            "asset": "USDT",
            "network": "eip155:1",
            "name": "Ethereum USDT",
            "contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "decimals": 6,
            "verification": "permit2",
            "kind": "erc20",
        },
        "ETH": {
            "asset": "ETH",
            "network": "eip155:1",
            "name": "Ethereum ETH",
            "contract": "",
            "decimals": 18,
            "verification": "native",
            "kind": "native",
        },
        "WETH": {
            "asset": "WETH",
            "network": "eip155:1",
            "name": "Ethereum WETH",
            "contract": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
    },
    "eip155:42161": {
        "USDC": {
            "asset": "USDC",
            "network": "eip155:42161",
            "name": "Arbitrum USDC",
            "contract": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "decimals": 6,
            "verification": "eip3009",
            "kind": "erc20",
        },
        "USDT": {
            "asset": "USDT",
            "network": "eip155:42161",
            "name": "Arbitrum USDT",
            "contract": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
            "decimals": 6,
            "verification": "permit2",
            "kind": "erc20",
        },
        "ARB": {
            "asset": "ARB",
            "network": "eip155:42161",
            "name": "Arbitrum ARB",
            "contract": "0x912CE59144191C1204E64559FE8253a0e49E6548",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
        "ETH": {
            "asset": "ETH",
            "network": "eip155:42161",
            "name": "Arbitrum ETH",
            "contract": "",
            "decimals": 18,
            "verification": "native",
            "kind": "native",
        },
        "WETH": {
            "asset": "WETH",
            "network": "eip155:42161",
            "name": "Arbitrum WETH",
            "contract": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
    },
    "eip155:10": {
        "USDC": {
            "asset": "USDC",
            "network": "eip155:10",
            "name": "Optimism USDC",
            "contract": "0x0b2C639c533813f4Aa9D7837CAf62653d097F85F",
            "decimals": 6,
            "verification": "eip3009",
            "kind": "erc20",
        },
        "USDT": {
            "asset": "USDT",
            "network": "eip155:10",
            "name": "Optimism USDT",
            "contract": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
            "decimals": 6,
            "verification": "permit2",
            "kind": "erc20",
        },
        "ETH": {
            "asset": "ETH",
            "network": "eip155:10",
            "name": "Optimism ETH",
            "contract": "",
            "decimals": 18,
            "verification": "native",
            "kind": "native",
        },
        "WETH": {
            "asset": "WETH",
            "network": "eip155:10",
            "name": "Optimism WETH",
            "contract": "0x4200000000000000000000000000000000000006",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
    },
    "eip155:137": {
        "USDC": {
            "asset": "USDC",
            "network": "eip155:137",
            "name": "Polygon USDC",
            "contract": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            "decimals": 6,
            "verification": "eip3009",
            "kind": "erc20",
        },
        "USDT": {
            "asset": "USDT",
            "network": "eip155:137",
            "name": "Polygon USDT",
            "contract": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
            "decimals": 6,
            "verification": "permit2",
            "kind": "erc20",
        },
        "POL": {
            "asset": "POL",
            "network": "eip155:137",
            "name": "Polygon POL",
            "contract": "",
            "decimals": 18,
            "verification": "native",
            "kind": "native",
        },
        "WETH": {
            "asset": "WETH",
            "network": "eip155:137",
            "name": "Polygon WETH",
            "contract": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
            "decimals": 18,
            "verification": "permit2",
            "kind": "erc20",
        },
    },
    "solana:mainnet": {
        "USDC": {
            "asset": "USDC",
            "network": "solana:mainnet",
            "name": "Solana USDC",
            "contract": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "decimals": 6,
            "verification": "spl",
            "kind": "spl",
        },
        "USDT": {
            "asset": "USDT",
            "network": "solana:mainnet",
            "name": "Solana USDT",
            "contract": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            "decimals": 6,
            "verification": "spl",
            "kind": "spl",
        },
        "SOL": {
            "asset": "SOL",
            "network": "solana:mainnet",
            "name": "Solana SOL",
            "contract": "",
            "decimals": 9,
            "verification": "native",
            "kind": "native",
        },
    },
    "tron:mainnet": {
        "USDT": {
            "asset": "USDT",
            "network": "tron:mainnet",
            "name": "TRON USDT",
            "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "decimals": 6,
            "verification": "trc20",
            "kind": "trc20",
        },
        "TRX": {
            "asset": "TRX",
            "network": "tron:mainnet",
            "name": "TRON TRX",
            "contract": "",
            "decimals": 6,
            "verification": "native",
            "kind": "native",
        },
    },
}

# Verification status per chain family — what is REAL vs scaffolded.
# ``status`` is the machine-readable label exposed by the health + pricing
# endpoints: "live" (EVM — EIP-7702 self-verify + facilitators; Solana —
# SPL RPC verifier, getTransaction jsonParsed USDC transferChecked; TRON —
# TRC-20 Grid verifier, gettransactioninfobyid USDT Transfer event).
VERIFICATION_STATUS: dict[str, dict[str, Any]] = {
    "evm": {
        "status": "live",
        "real": True,
        "scaffolded": False,
        "note": "EIP-7702 self-verify (receipt + payTo/amount) and external facilitators",
    },
    "solana": {
        "status": "live",
        "real": True,
        "scaffolded": False,
        "note": "SPL RPC verifier — getTransaction jsonParsed USDC transferChecked to the configured Solana wallet",
    },
    "tron": {
        "status": "scaffolded:needs_facilitator",
        "real": False,
        "scaffolded": True,
        "note": "TRON scaffolded — no TRC-20 settlement verifier is wired/exposed yet; do not claim verified",
    },
}

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

_STABLECOIN_ASSETS = {X402Asset.USDC.value, X402Asset.USDT.value, X402Asset.DAI.value}

# Async price cache: (source_key, asset, network) -> (monotonic_ts, usd).
# Keying by source means a test/operator toggling providers can never read a
# stale quote from a different provider.
_oracle_cache: dict[tuple[str, str, str], tuple[float, float]] = {}


def clear_price_cache() -> None:
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
    asset = os.getenv("PRY_X402_ORACLE_PROBE_ASSET", "ETH")
    quote = await get_asset_usd_price(asset)
    return quote.source == "oracle", oracle_source_label()


def normalize_network_id(network: str) -> str:
    """Map a legacy x402 network name (or CAIP-2 id) to the CAIP-2 id.

    Unknown values pass through unchanged so callers can decide how to treat
    them; empty input stays empty.
    """
    if not network:
        return network
    return CAIP2_NETWORK_IDS.get(network.lower(), network)


def network_family(network: str) -> str:
    """Return the chain family for a network: evm | solana | tron | unknown."""
    network_id = normalize_network_id(network)
    if ":" not in network_id:
        return "unknown"
    prefix = network_id.split(":", 1)[0]
    if prefix == "eip155":
        return "evm"
    if prefix == "solana":
        return "solana"
    if prefix == "tron":
        return "tron"
    return "unknown"


def resolve_pay_to(
    network: str,
    wallets: dict[str, str] | None = None,
    evm_wallet: str | None = None,
) -> str:
    """Resolve the payTo (receiving) address for ``network`` — family-aware.

    EVM networks (eip155:*) use the per-network override from the wallet map
    (``PRY_X402_WALLET_BASE`` etc.) or, failing that, the shared EVM treasury
    ``evm_wallet`` (defaults to ``X402_WALLET``, itself gopass
    ``evm_treasury_address`` by default). Solana resolves to
    ``PRY_X402_WALLET_SOLANA`` and TRON to ``PRY_X402_WALLET_TRON``.

    There is NO cross-family fallback: a Solana/TRON invoice NEVER emits an
    EVM hex address and an EVM invoice never emits a base58 address. The
    resolved address is format-checked against its family
    (``is_evm_address`` / ``is_solana_address`` / ``is_tron_address``);
    unconfigured, placeholder, or shape-mismatched values return "" so
    callers fail closed instead of advertising a fake payTo.

    ``wallets``/``evm_wallet`` override the default wallet sources. Callers
    that expose module-level wallet attributes (e.g. packs.py) pass them
    explicitly so the resolution seam stays patchable in tests.
    """
    network_wallets = X402_NETWORK_WALLETS if wallets is None else wallets
    evm = X402_WALLET if evm_wallet is None else evm_wallet
    family = network_family(network)
    if family == "solana":
        pay_to = network_wallets.get("solana:mainnet", "")
        if not is_solana_address(pay_to):
            return ""
    elif family == "tron":
        pay_to = network_wallets.get("tron:mainnet", "")
        if not is_tron_address(pay_to):
            return ""
    elif family == "evm":
        network_id = normalize_network_id(network)
        pay_to = network_wallets.get(network_id) or evm
        if not is_evm_address(pay_to):
            return ""
    else:
        return ""
    if pay_to in X402_PLACEHOLDER_WALLETS:
        return ""
    return pay_to


def treasury_wallets() -> dict[str, str]:
    """Return the configured per-chain treasury addresses for the pricing endpoint.

    Reads the operator env vars directly (``PRY_X402_WALLET`` for EVM,
    ``PRY_X402_WALLET_SOLANA``, ``PRY_X402_WALLET_TRON``) so the live
    ``/v1/x402/pricing`` response surfaces the ACTUAL configured treasuries
    instead of a stale/empty module-level snapshot. Each address is
    format-validated through :func:`resolve_pay_to` (family-aware, fail
    closed) so an unconfigured or malformed wallet is reported as ``""``
    rather than a fake payTo.
    """
    return {
        "evm": resolve_pay_to("base", wallets={}, evm_wallet=os.getenv("PRY_X402_WALLET", "")),
        "solana": resolve_pay_to(
            "solana:mainnet",
            wallets={"solana:mainnet": os.getenv("PRY_X402_WALLET_SOLANA", "")},
        ),
        "tron": resolve_pay_to(
            "tron:mainnet",
            wallets={"tron:mainnet": os.getenv("PRY_X402_WALLET_TRON", "")},
        ),
    }


def network_verification_status(network: str) -> str:
    """Return the verification-status label for a network.

    ``"live"`` for EVM chains (EIP-7702 self-verify + facilitators) and
    Solana (SPL RPC verifier — getTransaction jsonParsed USDC
    transferChecked); ``"scaffolded:needs_facilitator"`` for TRON
    (structure/price/asset validated; on-chain settlement NOT verified until
    a facilitator impl or TRC-20 verifier is registered); ``"unknown"``
    otherwise. Exposed by the health + pricing endpoints so operators never
    mistake a scaffold for real settlement verification.
    """
    status = VERIFICATION_STATUS.get(network_family(network), {})
    return str(status.get("status", "unknown"))


def resolve_asset_entry(network: str, asset: str) -> dict[str, Any] | None:
    """Look up the canonical SUPPORTED_ASSETS entry for (network, asset).

    Accepts legacy network names or CAIP-2 ids. Returns None when the pair is
    not in the acceptance table.
    """
    network_id = normalize_network_id(network)
    if not network_id or not asset:
        return None
    return SUPPORTED_ASSETS.get(network_id, {}).get(asset.upper())


def is_asset_supported(network: str, asset: str) -> bool:
    """Return True when (network, asset) is in the canonical acceptance table."""
    return resolve_asset_entry(network, asset) is not None


def usd_per_unit_for(asset: str) -> float | None:
    """Return the USD value of one unit of ``asset`` (None when unknown)."""
    value = X402_ASSET_USD_PER_UNIT.get(asset.upper())
    if value is None or value <= 0:
        return None
    return value


def asset_to_atomic(
    amount_usd: float,
    asset: str = X402_DEFAULT_ASSET,
    network: str = "",
) -> int:
    """Convert a USD amount to atomic units for (network, asset).

    Uses the canonical SUPPORTED_ASSETS table when the pair is known so
    decimals and USD-per-unit come from one place; falls back to the legacy
    ASSET_DECIMALS table with 1:1 USD pricing for unknown pairs.
    """
    entry = resolve_asset_entry(network, asset)
    if entry:
        decimals = int(entry.get("decimals", ASSET_DECIMALS.get(asset.upper(), 6)))
    else:
        decimals = ASSET_DECIMALS.get(asset.upper(), 6)
    unit_usd = usd_per_unit_for(asset) or 1.0
    return round(amount_usd / unit_usd * (10**decimals))


def flatten_supported_assets() -> list[dict[str, Any]]:
    """Flatten SUPPORTED_ASSETS into a single list of asset entries."""
    flat: list[dict[str, Any]] = []
    for network_id, assets in SUPPORTED_ASSETS.items():
        for asset, entry in assets.items():
            flat.append(
                {
                    "asset": asset,
                    "network": network_id,
                    "name": entry.get("name", asset),
                    "contract": entry.get("contract", ""),
                    "decimals": entry.get("decimals", 6),
                    "verification": entry.get("verification", ""),
                    "kind": entry.get("kind", ""),
                }
            )
    return flat


def _to_atomic(amount_usd: float, asset: str = X402_DEFAULT_ASSET) -> int:
    """Convert USD amount to atomic units for the given asset."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return int(amount_usd * (10**decimals))


def _from_atomic(amount_atomic: int, asset: str = X402_DEFAULT_ASSET) -> float:
    """Convert atomic units back to USD-normalized float."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return float(round(amount_atomic / (10**decimals), decimals))


# ── Server attestation over the payment-required challenge ─────────────────
# Audit #1 (HIGH): the x402 payment-required body was unsigned — a MITM /
# proxy / shared cache could rewrite ``payToAddress`` (or the amount) and a
# payer would happily sign/authorize the attacker's address. This block
# DOMAIN-SEPARATES and SIGNS the canonical (payTo, amount, network, nonce,
# issued_at, operation) of every accept with a server key, so a client or a
# verify/settle path can recompute the digest and confirm the payTo came from
# US.
#
# Scheme (v1): ``keccak256-ecdsa-secp256k1-v1``. The canonical payload is a
# stable, ordered JSON list (no dict-key ordering ambiguity), keccak256-hashed,
# then signed with the server's secp256k1 key using the same ``eth_keys``
# backend the self-facilitator uses for EIP-3009. The recoverable 65-byte
# signature (r||s||v) is embedded per accept under ``body["attestation"]``; a
# verifier recomputes the digest and ecrecovers the signer, rejecting any
# accept whose payTo/amount/network/operation/resource/asset changed.
#
# Key source (NEVER hardcoded), precedence:
#   1. ``PRY_X402_ATTEST_KEY``      - explicit 32-byte private key hex (with/without 0x)
#   2. ``PRY_X402_FACILITATOR_KEY`` - reuse the EIP-3009 facilitator key
#   3. ``PRY_X402_ATTEST_SECRET``   - derive a key via sha256(secret) (deterministic)
#   (none)                          - body is emitted UNATTESTED (backward compatible);
#                                     ``verify_payment_required_attestation`` reports
#                                     ``attested=False`` and callers decide whether to enforce.
#
# BACKWARD COMPAT: attestation is attached ONLY at encode time
# (``_encode_payment_required_body``) over the accepts ACTUALLY being encoded,
# so callers that compact/trim the accepts (x402 middleware enforcement) always
# get a self-consistent signature. ``build_payment_required`` still returns a
# clean body; the encode step signs a COPY and never mutates the caller's dict.

X402_ATTEST_DOMAIN: str = "pry-x402/attestation/v1"
X402_ATTEST_ALGORITHM: str = "keccak256-ecdsa-secp256k1-v1"
X402_ATTEST_VERSION: int = 1
X402_ATTEST_KEY_ENV: str = "PRY_X402_ATTEST_KEY"
X402_ATTEST_SECRET_ENV: str = "PRY_X402_ATTEST_SECRET"  # noqa: S105 - env var NAME, never a value

# Mutable per-process cache of the resolved key. Cleared on module reload
# (tests), so a reload + env change re-derives it. None = unconfigured.
_attest_key_cache: Any = None


def _attestation_private_key() -> Any:
    """Resolve the attestation private key (cached); None when unconfigured."""
    global _attest_key_cache
    if _attest_key_cache is not None:
        return _attest_key_cache
    if not _eth_keys:
        return None
    raw = os.getenv(X402_ATTEST_KEY_ENV, "").strip()
    if raw:
        raw = raw[2:] if raw.lower().startswith("0x") else raw
        try:
            _attest_key_cache = _eth_keys.PrivateKey(bytes.fromhex(raw))
            return _attest_key_cache
        except (ValueError, TypeError):
            logger.warning("x402_attest_key_invalid_ignored", extra={"env": X402_ATTEST_KEY_ENV})
    fac = os.getenv("PRY_X402_FACILITATOR_KEY", "").strip()
    if fac:
        fac = fac[2:] if fac.lower().startswith("0x") else fac
        try:
            _attest_key_cache = _eth_keys.PrivateKey(bytes.fromhex(fac))
            return _attest_key_cache
        except (ValueError, TypeError):
            logger.warning(
                "x402_attest_key_invalid_ignored", extra={"env": "PRY_X402_FACILITATOR_KEY"}
            )
    secret = os.getenv(X402_ATTEST_SECRET_ENV, "").strip()
    if secret:
        # Derive a key deterministically from a configured secret. Never hardcoded.
        _attest_key_cache = _eth_keys.PrivateKey(hashlib.sha256(secret.encode()).digest())
        return _attest_key_cache
    return None


def attestation_signer_address() -> str:
    """Return the attestation signer checksum address ("" when unconfigured)."""
    key = _attestation_private_key()
    if key is None:
        return ""
    return key.public_key.to_address()


def _attestation_payload(
    issued_at: int,
    nonce: str,
    index: int,
    accept: dict[str, Any],
) -> bytes:
    """Canonical, domain-separated bytes for one accept.

    Ordered JSON list (stable; dict keys are not signed directly so there is
    no ordering ambiguity). A verifier MUST rebuild the exact same list from
    the accept plus the top-level ``issued_at``/``nonce`` — any change to
    payTo, amount, network, operation, resource or asset flips the digest.
    """
    extra = accept.get("extra") if isinstance(accept.get("extra"), dict) else {}
    return json.dumps(
        [
            X402_ATTEST_DOMAIN,
            int(X402_ATTEST_VERSION),
            int(issued_at),
            str(nonce),
            int(index),
            str(accept.get("payToAddress", "")),
            str(accept.get("maxAmountRequired", "")),
            str(normalize_network_id(str(accept.get("network", "")))),
            str(extra.get("operation", "") or accept.get("operation", "")),
            str(accept.get("resource", "")),
            str(accept.get("asset", "")),
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def _attestation_digest(issued_at: int, nonce: str, index: int, accept: dict[str, Any]) -> bytes:
    return _keccak(_attestation_payload(issued_at, nonce, index, accept))


def attest_payment_required(body: dict[str, Any]) -> dict[str, Any]:
    """Return ``body`` with a server attestation attached (non-mutating, idempotent).

    When no attestation key is configured, or ``body`` already carries an
    ``attestation``, ``body`` is returned unchanged (backward compatible).
    Otherwise a shallow copy is produced with ``body["attestation"]`` holding
    the domain, version, algorithm, nonce, ``issued_at``, signer address and a
    per-accept recoverable ECDSA signature. The caller's dict is never mutated
    so compaction/trim consumers keep the clean body.
    """
    if not isinstance(body, dict):
        return body
    if body.get("attestation") is not None:
        return body
    key = _attestation_private_key()
    if key is None:
        return body
    accepts = body.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        return body  # nothing to attest
    nonce = uuid.uuid4().hex
    issued_at = int(time.time())
    signer = key.public_key.to_address()
    signatures: list[dict[str, Any]] = []
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            continue
        digest = _attestation_digest(issued_at, nonce, index, accept)
        sig = key.sign_msg_hash(digest)
        signatures.append({"index": index, "signature": sig.to_bytes().hex()})
    attested = dict(body)
    attested["attestation"] = {
        "version": X402_ATTEST_VERSION,
        "algorithm": X402_ATTEST_ALGORITHM,
        "domain": X402_ATTEST_DOMAIN,
        "nonce": nonce,
        "issued_at": issued_at,
        "signer": signer,
        "accepts": signatures,
    }
    return attested


def verify_payment_required_attestation(
    body: dict[str, Any],
    expected_signer: str = "",
) -> dict[str, Any]:
    """Verify the server attestation on a payment-required body.

    Returns ``{"verified", "reason", "attested", "signer", "signer_ok"}``.

    - ``attested=False`` - no ``attestation`` on the body (no server key was
      configured at issue time). Callers decide whether to enforce; this is
      the backward-compatible path.
    - ``verified=True`` - every accept's signature validates against the
      recomputed digest AND the ecrecovered signer matches the embedded
      ``signer`` AND (when ``expected_signer`` is supplied) that signer equals
      ``expected_signer`` (trusted out-of-band). This is what a settle/verify
      path should require before trusting ``payToAddress``.
    """
    if not isinstance(body, dict):
        return {
            "verified": False,
            "reason": "body not a mapping",
            "attested": False,
            "signer": "",
            "signer_ok": False,
        }
    attest = body.get("attestation")
    if not isinstance(attest, dict):
        return {
            "verified": False,
            "reason": "no attestation present",
            "attested": False,
            "signer": "",
            "signer_ok": False,
        }
    signer = str(attest.get("signer", ""))
    if not _eth_keys:
        return {
            "verified": False,
            "reason": "attestation crypto unavailable",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    if int(attest.get("version", 0)) != X402_ATTEST_VERSION:
        return {
            "verified": False,
            "reason": "unsupported attestation version",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    if attest.get("algorithm") != X402_ATTEST_ALGORITHM:
        return {
            "verified": False,
            "reason": "unsupported attestation algorithm",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    nonce = str(attest.get("nonce", ""))
    issued_at = int(attest.get("issued_at", 0) or 0)
    sig_map = {
        int(s.get("index", -1)): str(s.get("signature", ""))
        for s in attest.get("accepts", [])
        if isinstance(s, dict)
    }
    accepts = body.get("accepts")
    if not isinstance(accepts, list):
        return {
            "verified": False,
            "reason": "no accepts to verify",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            return {
                "verified": False,
                "reason": f"accept {index} not a mapping",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        raw_sig = sig_map.get(index, "")
        if not raw_sig:
            return {
                "verified": False,
                "reason": f"missing signature for accept {index}",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        try:
            signature = _eth_keys.Signature(bytes.fromhex(raw_sig))
            digest = _attestation_digest(issued_at, nonce, index, accept)
            recovered = signature.recover_public_key_from_msg_hash(digest).to_address()
        except (ValueError, TypeError):
            return {
                "verified": False,
                "reason": f"invalid signature for accept {index}",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        if not signer or recovered != signer:
            return {
                "verified": False,
                "reason": (
                    f"signature mismatch for accept {index} (tampered payTo/amount/network?)"
                ),
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
    signer_ok = True
    if expected_signer:
        signer_ok = signer.lower() == expected_signer.lower()
        if not signer_ok:
            return {
                "verified": False,
                "reason": "signer not in trusted set",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
    return {
        "verified": True,
        "reason": "",
        "attested": True,
        "signer": signer,
        "signer_ok": signer_ok,
    }


def _encode_payment_required_body(body: dict[str, Any]) -> str:
    """Base64-encode the PaymentRequired body per x402 spec.

    Attaches a server attestation over the accepts ACTUALLY being encoded
    (see :func:`attest_payment_required`) so a client/verifier can
    cryptographically confirm that ``payToAddress`` came from the server —
    closing audit #1 (the body was previously unsigned). Non-mutating and
    idempotent; when no attestation key is configured the body is encoded
    exactly as before.
    """
    attested = attest_payment_required(body)
    return base64.b64encode(json.dumps(attested).encode()).decode()


def _decode_payment_signature(header: str) -> dict[str, Any] | None:
    """Decode the PAYMENT-SIGNATURE header per x402 spec."""
    try:
        return cast("dict[str, Any]", json.loads(base64.b64decode(header).decode()))
    except (ValueError, OSError):
        return None


def _encode_payment_response(settlement: dict[str, Any]) -> str:
    """Base64-encode the PaymentResponse (settlement receipt) per x402 spec."""
    return base64.b64encode(json.dumps(settlement).encode()).decode()


def _default_networks_for_asset(asset: str) -> list[str]:
    """Return sensible default networks for an asset."""
    asset = asset.upper()
    mapping: dict[str, list[str]] = {
        X402Asset.USDC.value: [
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.SOLANA.value,
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.USDT.value: [
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.TRON.value,
            X402Network.SOLANA.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.DAI.value: [
            X402Network.ETHEREUM.value,
            X402Network.POLYGON.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.BASE.value,
        ],
        X402Asset.ETH.value: [
            X402Network.ETHEREUM.value,
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
        ],
        X402Asset.WETH.value: [
            X402Network.ETHEREUM.value,
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
        ],
        X402Asset.ARB.value: [X402Network.ARBITRUM.value],
        X402Asset.SOL.value: [X402Network.SOLANA.value],
        X402Asset.MATIC.value: [X402Network.POLYGON.value],
        X402Asset.POL.value: [X402Network.POLYGON.value],
        X402Asset.TRX.value: [X402Network.TRON.value],
        X402Asset.BTC.value: [X402Network.BITCOIN.value],
        X402Asset.LTC.value: [X402Network.LITECOIN.value],
        X402Asset.DOGE.value: [X402Network.DOGECOIN.value],
    }
    return mapping.get(asset, [X402Network.BASE.value])


def _asset_on_network(asset: str, network: str) -> bool:
    """Check whether an asset is generally supported on a network."""
    return network in _default_networks_for_asset(asset)


def resolve_price_usd(
    operation: str,
    network: str = "",
    asset: str = "",
) -> float:
    """Return the SERVER-side authoritative price (USD) for an operation.

    Never trust a client-supplied ``amount_usd``: this is the number the
    server enforces. Returns 0.0 for unknown operations (callers must decide
    how to treat those).

    When ``network`` (legacy name or CAIP-2 id) and ``asset`` are supplied, a
    per-network/per-asset override in ``X402_PRICING[operation]["prices"]``
    takes precedence; otherwise the operation's base ``price_usd`` applies.
    """
    info = X402_PRICING.get(operation) or {}
    if network and asset:
        network_id = normalize_network_id(network)
        raw_prices = info.get("prices")
        prices = raw_prices if isinstance(raw_prices, dict) else {}
        raw_network_prices = prices.get(network_id)
        network_prices = raw_network_prices if isinstance(raw_network_prices, dict) else {}
        override = network_prices.get(asset.upper())
        if override is not None:
            return float(override)
    return float(info.get("price_usd", 0.0))


def validate_client_amount(
    operation: str,
    client_amount_usd: float,
    asset: str = X402_DEFAULT_ASSET,
    network: str = "",
) -> tuple[bool, str]:
    """Reject client-supplied underpayment against the server-side price.

    Comparison happens in atomic units so float drift cannot be exploited.
    Returns ``(ok, reason)``. ``ok=False`` means the client offered LESS than
    the authoritative price (or a non-finite/negative amount) — the payment
    must be refused. Overpayment is allowed (client may pay more).

    When ``network`` is given and the (network, asset) pair is in the
    canonical SUPPORTED_ASSETS table, the table's decimals and USD-per-unit
    conversion are used (so non-1:1 assets like ETH/ARB quote correctly);
    otherwise the legacy 1:1 ASSET_DECIMALS path is used.
    """
    if client_amount_usd is None or not math.isfinite(float(client_amount_usd)):
        return False, "invalid (non-finite) client amount"
    if client_amount_usd < 0:
        return False, f"negative client amount {client_amount_usd}"
    required = resolve_price_usd(operation, network=network, asset=asset)
    if required <= 0:
        # No server price configured for this operation — nothing to enforce.
        return True, ""
    try:
        if resolve_asset_entry(network, asset) is not None:
            required_atomic = asset_to_atomic(required, asset, network)
            client_atomic = asset_to_atomic(client_amount_usd, asset, network)
        else:
            required_atomic = _to_atomic(required, asset)
            client_atomic = _to_atomic(client_amount_usd, asset)
    except (ValueError, TypeError):
        return False, "invalid amount/asset for pricing check"
    if client_atomic < required_atomic:
        return (
            False,
            f"underpayment: client supplied {client_amount_usd} USD, "
            f"server requires {required} USD for '{operation}'",
        )
    return True, ""


def build_multi_asset_accepts(
    operation: str,
    resource: str = "",
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the accepts list covering every quotable asset in SUPPORTED_ASSETS.

    Each option is keyed by CAIP-2 network id and quotes the USD-equivalent
    atomic amount for the operation's server-side price (per-network
    ``prices`` overrides in X402_PRICING apply). Assets without a configured
    USD-per-unit conversion are skipped — they cannot be quoted honestly.

    ``preferred_networks``/``preferred_assets`` narrow the acceptance surface
    to the requested networks/assets (as legacy names or CAIP-2 ids). When
    omitted, the full SUPPORTED_ASSETS table is advertised.
    """
    pref_networks = {normalize_network_id(n) for n in (preferred_networks or []) if n}
    pref_assets = {a.upper() for a in (preferred_assets or []) if a}
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    resource_url = resource or f"https://pry.dev/api/{operation}"
    accepts: list[dict[str, Any]] = []
    for network_id, assets in SUPPORTED_ASSETS.items():
        if pref_networks and network_id not in pref_networks:
            continue
        for asset, entry in assets.items():
            if pref_assets and asset.upper() not in pref_assets:
                continue
            price_usd = resolve_price_usd(operation, network=network_id, asset=asset)
            unit_usd = usd_per_unit_for(asset)
            if not unit_usd or price_usd <= 0:
                continue
            amount = asset_to_atomic(price_usd, asset, network_id)
            pay_to = resolve_pay_to(network_id)  # family-aware; "" when unconfigured
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": network_id,
                    "maxAmountRequired": str(amount),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": pay_to,
                    "asset": asset,
                    "extra": {
                        "name": entry.get("name", asset),
                        "version": "2",
                        "operation": operation,
                        "caip2": network_id,
                        "verification": entry.get("verification", ""),
                        "contract": entry.get("contract", ""),
                        "decimals": entry.get("decimals", 6),
                        "priceUsd": price_usd,
                        "usdPerUnit": unit_usd,
                        "usdPerUnitSource": (
                            "stablecoin" if asset in _STABLECOIN_ASSETS else "static-default"
                        ),
                    },
                }
            )
    return accepts


def build_payment_required(
    operation: str,
    resource: str = "",
    accepts: list[dict[str, Any]] | None = None,
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
    multi_asset: bool = False,
) -> dict[str, Any]:
    """Build a spec-compliant x402 PaymentRequired response.

    Returns a dict that should be:
    1. Returned as the body of the 402 response (JSON)
    2. Base64-encoded and put in the PAYMENT-REQUIRED header

    Args:
        operation: The operation being paid for (e.g., "scrape")
        resource: Full URL of the protected resource
        accepts: List of payment options (if None, generates defaults)
        description: Human-readable description
        mime_type: Expected response MIME type
        preferred_networks: Networks to prioritize in accepts
        preferred_assets: Assets to prioritize in accepts
        multi_asset: When True (and ``accepts`` is None) build options from
            the canonical SUPPORTED_ASSETS table — every quotable
            network/asset keyed by CAIP-2 network id — and attach the
            supported_assets/networks tables to the body so clients see the
            full multi-chain acceptance surface. Default False keeps the V1
            legacy single-asset shape.
    """
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    amount_atomic = _to_atomic(price_info["price_usd"], X402_DEFAULT_ASSET)
    resource_url = resource or f"https://pry.dev/api/{operation}"

    if accepts is None:
        if multi_asset:
            accepts = build_multi_asset_accepts(
                operation,
                resource=resource_url,
                description=description,
                mime_type=mime_type,
                preferred_networks=preferred_networks,
                preferred_assets=preferred_assets,
            )
        else:
            networks = preferred_networks or _default_networks_for_asset(X402_DEFAULT_ASSET)
            assets = preferred_assets or [X402_DEFAULT_ASSET]
            accepts = []
            for network in networks:
                for asset in assets:
                    if not _asset_on_network(asset, network):
                        continue
                    amount = _to_atomic(price_info["price_usd"], asset)
                    pay_to = resolve_pay_to(network)  # family-aware; "" when unconfigured
                    accepts.append(
                        {
                            "scheme": X402Scheme.EXACT.value,
                            "network": network,
                            "maxAmountRequired": str(amount),
                            "resource": resource_url,
                            "description": description or price_info.get("description", operation),
                            "mimeType": mime_type,
                            "payToAddress": pay_to,
                            "asset": asset,
                            "extra": {"name": asset, "version": "2", "operation": operation},
                        }
                    )
        if not accepts:
            # Final fallback so we never return an empty accepts array
            fallback_pay_to = resolve_pay_to(X402Network.BASE.value)
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": X402Network.BASE.value,
                    "maxAmountRequired": str(amount_atomic),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": fallback_pay_to,
                    "asset": X402_DEFAULT_ASSET,
                    "extra": {"name": X402_DEFAULT_ASSET, "version": "2", "operation": operation},
                }
            )

    body: dict[str, Any] = {
        "x402Version": 1,
        "accepts": accepts,
    }
    if multi_asset:
        # Multi-chain acceptance surface so agents can see every network/asset
        # they may pay with (additive — spec clients ignore unknown keys).
        body["networks"] = SUPPORTED_NETWORKS
        body["supported_assets"] = flatten_supported_assets()
    return body


# These return the pre-spec response format. Prefer the spec-compliant methods
# above in new code.


def _legacy_payment_request(
    operation: str,
    metadata: dict[str, Any] | None = None,
    price_usd: float = 0.001,
    payment_id: str = "",
) -> dict[str, Any]:
    price_info = X402_PRICING.get(operation, {"price_usd": price_usd, "description": operation})
    return {
        "x402Version": 1,
        "payment_id": payment_id or uuid.uuid4().hex[:12],
        "scheme": X402Scheme.EXACT.value,
        "network": X402_DEFAULT_NETWORK,
        "resource": f"https://pry.dev/api/{operation}",
        "operation": operation,
        "description": price_info.get("description", operation),
        "maxAmountRequired": str(int(price_info["price_usd"] * 1_000_000)),
        "asset": X402Asset.USDC.value,
        "payTo": resolve_pay_to(X402_DEFAULT_NETWORK),
        "maxTimeoutSeconds": 60,
        "extra": metadata or {},
    }


def create_payment_request(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build a single-payment payment request dict.

    Returns the pre-spec shape used by /v1/x402/payment.
    """
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    req = _legacy_payment_request(operation, metadata=metadata)
    logger.info(
        "x402_payment_request_created",
        extra={"payment_id": req["payment_id"], "operation": operation},
    )
    return req


def require_payment_legacy(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build the pre-spec 402 response with X-Payment-Required header."""
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    return {
        "status_code": 402,
        "headers": {
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        },
        "body": {
            "error": "Payment Required",
            "x402": _legacy_payment_request(operation, metadata=metadata),
            "instructions": (
                "Send USDC payment to the wallet address, then call the API again "
                "with the X-Payment-Hash header."
            ),
        },
    }
