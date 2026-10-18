"""Crypto market dataset package for Pry.

Restores the ``datasets.crypto_market`` import path consumed by
``pry/api/routers/data/crypto_market.py``. The provider implementations
(and their never-raise contracts) remain in the canonical
:mod:`crypto_market` package; the submodules here are thin, logged
facades so there is exactly one implementation of each source.

Modules:
- :mod:`datasets.crypto_market.token_launches` — new tokens, new pairs,
  trending tokens (DexScreener → CoinGecko → CMC → Birdeye).
- :mod:`datasets.crypto_market.cex_listings` — CEX listing/delisting
  signals from free public exchange endpoints.
- :mod:`datasets.crypto_market.token_security` — GoPlus token risk scan
  with a local heuristic fallback.

All functions are async, return typed dicts/lists, and return an empty
result when an upstream is empty or unavailable — they never raise, so the
router answers 200 instead of 502.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.crypto_market.cex_listings import (
    DEFAULT_LOOKBACK_HOURS,
    SUPPORTED_EXCHANGES,
    get_listing_signals,
    get_recent_delistings,
)
from datasets.crypto_market.token_launches import (
    SUPPORTED_CHAINS,
    get_chain_context,
    get_new_pairs,
    get_new_tokens,
    get_trending_tokens,
)
from datasets.crypto_market.token_security import scan_token

__all__ = [
    "DEFAULT_LOOKBACK_HOURS",
    "SUPPORTED_CHAINS",
    "SUPPORTED_EXCHANGES",
    "get_chain_context",
    "get_listing_signals",
    "get_new_pairs",
    "get_new_tokens",
    "get_recent_delistings",
    "get_trending_tokens",
    "scan_token",
]
