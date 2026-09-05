"""Birdeye token-list provider (needs a free ``PRY_BIRDEYE_API_KEY``).

Honest flags: the token list carries no creation timestamp (recency is
last-trade based) and no live price — ``price_usd`` defaults to 0.0 and
``min_age_minutes`` filters on the recency proxy.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from crypto_market._http import _get_json
from crypto_market._normalize import _api_key, _created_epoch, _entry_age_minutes, _f, _iso
from crypto_market._registry import BIRDEYE_CHAIN_IDS, SUPPORTED_CHAINS

logger = logging.getLogger(__name__)

BIRDEYE_TOKENLIST_URL = "https://public-api.birdeye.so/defi/tokenlist"


def _normalize_birdeye_token(token: dict[str, Any], chain: str) -> dict[str, Any] | None:
    """Normalize a Birdeye ``/defi/tokenlist`` token into the shared schema."""
    address = str(token.get("address") or "")
    symbol = str(token.get("symbol") or "")
    name = str(token.get("name") or "")
    if not address or (not symbol and not name):
        return None
    return {
        "chain": chain,
        "address": address,
        "symbol": symbol,
        "name": name,
        "pair_address": "",
        "created_at_utc": _iso(token.get("lastTradeUnixTime")),
        "price_usd": 0.0,  # tokenlist has no live price
        "liquidity_usd": _f(token.get("liquidity")),
        "volume_24h_usd": _f(token.get("v24hUSD")),
        "price_change_24h_pct": _f(token.get("v24hChangePercent")),
        "source": "birdeye",
    }


async def _birdeye_tokens_for_chain(chain: str) -> list[dict[str, Any]]:
    """Fetch one Birdeye token list page for ``chain`` (needs a free key)."""
    api_key = _api_key("PRY_BIRDEYE_API_KEY", "BIRDEYE_API_KEY")
    if not api_key:
        logger.info("crypto_market_birdeye_skipped_no_api_key")
        return []
    chain_id = BIRDEYE_CHAIN_IDS.get(chain)
    if not chain_id:
        return []
    data = await _get_json(
        BIRDEYE_TOKENLIST_URL,
        params={"limit": 50, "offset": 0, "sort_by": "v24hUSD", "sort_type": "desc"},
        headers={"X-API-KEY": api_key, "x-chain": chain_id},
    )
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    tokens = inner.get("tokens") if isinstance(inner, dict) else None
    if not isinstance(tokens, list):
        return []
    results: list[dict[str, Any]] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        normalized = _normalize_birdeye_token(token, chain)
        if normalized is not None:
            results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results


async def _new_tokens_birdeye(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """Birdeye token-list fallback (needs a free ``PRY_BIRDEYE_API_KEY``)."""
    chains = [chain] if chain is not None else list(SUPPORTED_CHAINS)
    results: list[dict[str, Any]] = []
    for name in chains:
        results.extend(await _birdeye_tokens_for_chain(name))
    if min_age_minutes > 0:
        results = [
            entry
            for entry in results
            if (age := _entry_age_minutes(entry)) is not None and age >= min_age_minutes
        ]
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


__all__ = [
    "_birdeye_tokens_for_chain",
    "_new_tokens_birdeye",
    "_normalize_birdeye_token",
]
