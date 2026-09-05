"""Pry — x402 TRON network/asset acceptance table.

Pure data module split out of ``networks.py``. Values are unchanged.
"""

from __future__ import annotations

from typing import Any

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

TRON_ASSETS: dict[str, dict[str, dict[str, Any]]] = {
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
