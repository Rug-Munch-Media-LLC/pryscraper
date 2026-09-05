"""Pry — x402 Solana network/asset acceptance table.

Pure data module split out of ``networks.py``. Values are unchanged.
"""

from __future__ import annotations

from typing import Any

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

SOLANA_ASSETS: dict[str, dict[str, dict[str, Any]]] = {
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
}
