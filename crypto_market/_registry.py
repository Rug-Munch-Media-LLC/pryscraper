"""Static data registries for crypto_market, loaded from ``_registry.json``.

Chain lists and provider id-mapping tables live in a JSON data file so
they can be updated without touching logic code. Everything here is
plain data — no I/O beyond one read at import time.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).with_name("_registry.json")
with _REGISTRY_PATH.open(encoding="utf-8") as _fh:
    _DATA: dict[str, object] = json.load(_fh)

SUPPORTED_CHAINS: tuple[str, ...] = tuple(_DATA["supported_chains"])  # type: ignore[arg-type]

# Birdeye chain id header values for our supported chains.
BIRDEYE_CHAIN_IDS: dict[str, str] = dict(_DATA["birdeye_chain_ids"])  # type: ignore[arg-type]

# DexScreener chain id -> CoinGecko platform id (used for chain attribution
# of CoinGecko results via /coins/list?include_platform=true).
COINGECKO_PLATFORMS: dict[str, str] = dict(_DATA["coingecko_platforms"])  # type: ignore[arg-type]

# CoinMarketCap platform id/name -> supported chain id.
CMC_PLATFORM_ALIASES: dict[str, str] = dict(_DATA["cmc_platform_aliases"])  # type: ignore[arg-type]

__all__ = [
    "BIRDEYE_CHAIN_IDS",
    "CMC_PLATFORM_ALIASES",
    "COINGECKO_PLATFORMS",
    "SUPPORTED_CHAINS",
]
