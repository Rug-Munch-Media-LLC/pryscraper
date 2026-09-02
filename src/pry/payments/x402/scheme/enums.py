"""Pry — x402 enums and asset metadata tables."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from enum import StrEnum


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

# Assets fixed at 1:1 USD (never quoted from the live oracle).
_STABLECOIN_ASSETS = {X402Asset.USDC.value, X402Asset.USDT.value, X402Asset.DAI.value}
