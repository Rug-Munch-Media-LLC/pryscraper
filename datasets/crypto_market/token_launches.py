"""Dataset facade — crypto token launches, pairs, and trending tokens.

The provider implementations and their never-raise guarantees live in the
canonical :mod:`crypto_market` package (DexScreener → CoinGecko →
CoinMarketCap → Birdeye fallback chain, shared ``pry.api.client`` pool,
per-request timeouts, retry/backoff). This module is the stable
``datasets.crypto_market`` import path used by the HTTP router, adding
structured logging at the dataset boundary without duplicating logic.

Every function returns a list of normalized dicts and returns ``[]`` on
upstream failure — it never raises.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from crypto_market.token_launches import (
    SUPPORTED_CHAINS,
    get_chain_context as _get_chain_context,
    get_new_pairs as _get_new_pairs,
    get_new_tokens as _get_new_tokens,
    get_trending_tokens as _get_trending_tokens,
)

logger = logging.getLogger(__name__)


def _with_created_alias(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the ``created_at`` alias declared by the MCP output schema."""
    return [
        item if "created_at" in item else {**item, "created_at": item.get("created_at_utc", "")}
        for item in items
    ]


async def get_new_tokens(
    chain: str = "all", limit: int = 50, min_age_minutes: int = 0
) -> list[dict[str, Any]]:
    """Newest tokens across supported chains; ``[]`` when all sources fail."""
    items = _with_created_alias(
        await _get_new_tokens(chain=chain, limit=limit, min_age_minutes=min_age_minutes)
    )
    logger.info(
        "crypto_market_dataset_new_tokens",
        extra={"chain": chain, "limit": limit, "count": len(items)},
    )
    return items


async def get_new_pairs(chain: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    """Newest liquidity pairs; ``[]`` when the upstream is empty or down."""
    items = _with_created_alias(await _get_new_pairs(chain=chain, limit=limit))
    logger.info(
        "crypto_market_dataset_new_pairs",
        extra={"chain": chain, "limit": limit, "count": len(items)},
    )
    return items


async def get_trending_tokens(chain: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Trending tokens; ``[]`` when the upstream is empty or down."""
    items = _with_created_alias(await _get_trending_tokens(chain=chain, limit=limit))
    logger.info(
        "crypto_market_dataset_trending_tokens",
        extra={"chain": chain, "limit": limit, "count": len(items)},
    )
    return items


# Chain TVL context is not part of the router contract; re-exported for parity.
get_chain_context = _get_chain_context

__all__ = [
    "SUPPORTED_CHAINS",
    "get_chain_context",
    "get_new_pairs",
    "get_new_tokens",
    "get_trending_tokens",
]
