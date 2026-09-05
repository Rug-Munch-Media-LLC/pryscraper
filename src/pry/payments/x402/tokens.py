"""Canonical ERC-20 token address tables for x402 settlement verification.

A successful receipt alone is NOT proof of payment — the tx must have been
sent TO one of these token contracts with a transfer() to our wallet for at
least the server-side price. Addresses are well-known mainnet addresses.

NOTE — Base USDT single source: the Base USDT entry is derived in the package
``__init__`` from SUPPORTED_ASSETS (x402/scheme.py) so the two tables can
never disagree. The V1 table previously hardcoded
0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb for Base USDT — an error: that
contract is DAI on Base ("Dai Stablecoin", 18 decimals, confirmed via
eth_call), not USDT. The authoritative address is the official bridged
Tether USD 0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

EIP7702_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        # USDT derived from SUPPORTED_ASSETS in the package __init__
        # (single source of truth).
    },
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    },
    "polygon": {
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
    },
    "arbitrum": {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    },
    "optimism": {
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097F85F",
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
    },
    "bnb": {
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
    },
    "avalanche": {
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
    },
    "base-sepolia": {
        "USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    },
}
