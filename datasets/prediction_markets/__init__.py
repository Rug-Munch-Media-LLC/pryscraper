"""Prediction-markets data package for Pry.

Aggregates live prediction-market data from Polymarket (Gamma API) and
Kalshi (public trade API v2) into one unified, normalized format so
consumers (MCP tools, x402-gated endpoints, alert bots) can import from
a single place:

* :mod:`prediction_markets.polymarket` — Gamma API ``/markets`` +
  ``/events`` fallback (no key, no quota).
* :mod:`prediction_markets.kalshi` — public trade API v2 ``/markets``
  (no key for public data).

Unified record shape: ``{market_id, source, question, category,
outcomes, yes_price, no_price, volume, liquidity, resolution_date, url,
active, last_update}``. Prices are 0-1 probabilities on both sources.

All functions are async and never raise — they return ``[]`` / ``{}``
on failure (network, quota, malformed payload). See each module's
docstring for exact result shapes.

Example:
    >>> from datasets.prediction_markets import get_prediction_markets
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from datasets.prediction_markets.kalshi import get_kalshi_market, get_kalshi_markets
from datasets.prediction_markets.polymarket import (
    get_polymarket_market,
    get_polymarket_markets,
)

logger = logging.getLogger(__name__)

_SOURCES = ("polymarket", "kalshi")


def _resolve_sources(source: str | None) -> list[str]:
    """Normalize the ``source`` parameter to a list of source names."""
    if not source or source.lower() in {"all", ""}:
        return list(_SOURCES)
    name = source.lower().strip()
    return [name] if name in _SOURCES else list(_SOURCES)


async def get_prediction_markets(
    category: str | None = None,
    source: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch live prediction markets, merged across sources.

    Args:
        category: Optional filter — ``"sports"``, ``"politics"``,
            ``"crypto"``, ``"economics"``, or ``"all"``/``None`` (default).
            Matched against each market's category and question text.
        source: ``"polymarket"``, ``"kalshi"``, or ``"all"`` (default).
            Unknown names fall back to all sources.
        limit: Max records to return (1-100), split across sources and
            sorted by volume.

    Returns:
        A list of unified market records (see package docstring), merged
        from every reachable source. ``[]`` on total failure. Never raises.
    """
    try:
        return await _get_prediction_markets(category, source, limit)
    except Exception:
        logger.exception(
            "prediction_markets_crashed",
            extra={"category": category, "source": source, "limit": limit},
        )
        return []


async def _get_prediction_markets(
    category: str | None, source: str | None, limit: int
) -> list[dict[str, Any]]:
    clamped = max(1, min(int(limit), 100))
    wanted = _resolve_sources(source)
    per_source = max(1, clamped)
    records: list[dict[str, Any]] = []
    if "polymarket" in wanted:
        records.extend(await get_polymarket_markets(category, per_source))
    if "kalshi" in wanted:
        records.extend(await get_kalshi_markets(category, per_source))
    records.sort(key=lambda record: float(record.get("volume") or 0.0), reverse=True)
    return records[:clamped]


async def get_prediction_market(
    market_id: str,
    source: str = "polymarket",
) -> dict[str, Any]:
    """Fetch a single prediction market by id/ticker.

    Args:
        market_id: Polymarket market id/slug or Kalshi ticker.
        source: Which upstream to query — ``"polymarket"`` (default) or
            ``"kalshi"``. Unknown names fall back to Polymarket.

    Returns:
        A unified market record (see package docstring) or ``{}`` on
        failure (unknown market, network error). Never raises.
    """
    try:
        name = (source or "polymarket").lower().strip()
        if name == "kalshi":
            return await get_kalshi_market(market_id)
        return await get_polymarket_market(market_id)
    except Exception:
        logger.exception(
            "prediction_market_crashed",
            extra={"market_id": market_id, "source": source},
        )
        return {}


__all__ = [
    "get_kalshi_market",
    "get_kalshi_markets",
    "get_polymarket_market",
    "get_polymarket_markets",
    "get_prediction_market",
    "get_prediction_markets",
]
