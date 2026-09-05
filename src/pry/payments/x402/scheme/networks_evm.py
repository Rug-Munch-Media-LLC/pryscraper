"""Pry — x402 EVM network/asset acceptance table (Base, Ethereum, Arbitrum, Optimism, Polygon).

Pure data module split out of ``networks.py``. Values are unchanged.
"""

from __future__ import annotations

from typing import Any

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

EVM_ASSETS: dict[str, dict[str, dict[str, Any]]] = {
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
}
