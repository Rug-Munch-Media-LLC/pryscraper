"""Pry — Crypto market intelligence router.

Exposes token-launch discovery, CEX listing/delisting signals, and token
security scans backed by the ``datasets.crypto_market`` package. Every
import is guarded: if a submodule is missing the endpoint still answers
200 with ``available: false`` and a ``reason`` instead of failing the
request, and an empty upstream result is a normal 200.

Endpoints:
- GET /v1/crypto/token-launches        — new tokens / pairs / trending
- GET /v1/crypto/cex-listings          — CEX listing signals
- GET /v1/crypto/token-security/{chain}/{address} — token security scan
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Query

from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Crypto Market"])

_KINDS = {"tokens", "pairs", "trending"}


def _crypto_module(module_name: str) -> Any:
    """Import a ``crypto_market`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.crypto_market.{module_name}")
    except ImportError:
        logger.warning("crypto_market_module_unavailable", extra={"module_name": module_name})
        return None


def _unavailable(module_name: str, **extra: Any) -> dict[str, Any]:
    """200-safe payload for a missing submodule (never a 502)."""
    logger.warning("crypto_market_endpoint_degraded", extra={"module_name": module_name})
    return {
        "success": True,
        "available": False,
        "reason": f"datasets.crypto_market.{module_name} is not available",
        "data": [],
        **extra,
    }


@router.get(
    "/v1/crypto/token-launches",
    tags=["Crypto Market"],
    summary="Get new crypto token launches, pairs, or trending tokens",
)
async def crypto_token_launches(
    chain: str = Query("all", description="Blockchain filter (e.g. 'solana', 'base', 'all')"),
    limit: int = Query(50, ge=1, le=500, description="Max results (default: 50)"),
    kind: str = Query("tokens", description="'tokens' | 'pairs' | 'trending'"),
) -> dict[str, Any]:
    """List newly created tokens, new liquidity pairs, or trending tokens."""
    if kind not in _KINDS:
        raise InvalidRequestError(f"kind must be one of {sorted(_KINDS)}")
    mod = _crypto_module("token_launches")
    if mod is None:
        return _unavailable("token_launches", chain=chain, kind=kind)
    fn = {
        "tokens": mod.get_new_tokens,
        "pairs": mod.get_new_pairs,
        "trending": mod.get_trending_tokens,
    }[kind]
    data = await fn(chain=chain, limit=limit)
    return {"success": True, "data": data, "chain": chain, "kind": kind}


@router.get(
    "/v1/crypto/cex-listings",
    tags=["Crypto Market"],
    summary="Get recent CEX listing and delisting signals",
)
async def crypto_cex_listings(
    exchanges: list[str] | None = Query(
        None, description="CEX names to filter by (e.g. binance, coinbase)"
    ),
    lookback_hours: int = Query(24, ge=1, le=720, description="Look back window in hours"),
) -> dict[str, Any]:
    """List recent centralized-exchange listing signals."""
    mod = _crypto_module("cex_listings")
    if mod is None:
        return _unavailable("cex_listings", lookback_hours=lookback_hours)
    data = await mod.get_listing_signals(exchanges=exchanges, lookback_hours=lookback_hours)
    return {"success": True, "data": data, "lookback_hours": lookback_hours}


@router.get(
    "/v1/crypto/token-security/{chain}/{address}",
    tags=["Crypto Market"],
    summary="Run a security scan on a token",
)
async def crypto_token_security(chain: str, address: str) -> dict[str, Any]:
    """Scan a token for rug-pull / honeypot risk signals."""
    mod = _crypto_module("token_security")
    if mod is None:
        return _unavailable("token_security", data={})
    data = await mod.scan_token(chain, address)
    return {"success": True, "data": data}
