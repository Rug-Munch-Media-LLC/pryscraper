"""Dataset facade — CEX listing and delisting signals.

The snapshot/diff engine and per-exchange fetchers live in the canonical
:mod:`crypto_market` package (free public exchange endpoints, no API keys).
This module is the stable ``datasets.crypto_market`` import path used by
the HTTP router and adds structured logging at the dataset boundary.

Signals are returned as a list of dicts (empty on failure or when no
change was observed). Nothing here raises on an upstream error.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from crypto_market.cex_listings import (
    DEFAULT_LOOKBACK_HOURS,
    SUPPORTED_EXCHANGES,
    get_listing_signals as _get_listing_signals,
    get_recent_delistings as _get_recent_delistings,
)

logger = logging.getLogger(__name__)


async def get_listing_signals(
    exchanges: list[str] | None = None, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
) -> list[dict[str, Any]]:
    """Newly listed symbols since the last poll; ``[]`` on failure."""
    signals = await _get_listing_signals(exchanges=exchanges, lookback_hours=lookback_hours)
    logger.info(
        "crypto_market_dataset_cex_signals",
        extra={
            "exchanges": exchanges or "all",
            "lookback_hours": lookback_hours,
            "count": len(signals),
        },
    )
    return signals


async def get_recent_delistings(
    exchanges: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Delisting signals since the last poll; ``[]`` on failure."""
    signals = await _get_recent_delistings(exchanges=exchanges)
    logger.info(
        "crypto_market_dataset_cex_delistings",
        extra={"exchanges": exchanges or "all", "count": len(signals)},
    )
    return signals


__all__ = [
    "DEFAULT_LOOKBACK_HOURS",
    "SUPPORTED_EXCHANGES",
    "get_listing_signals",
    "get_recent_delistings",
]
