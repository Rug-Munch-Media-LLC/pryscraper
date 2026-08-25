"""Pry — Crypto market intelligence router.

Exposes token-launch discovery, CEX listing/delisting signals, and token
security scans backed by the ``crypto_market`` subpackage (built in parallel
by other agents, so every import is guarded and degrades to 502 while a
module has not landed yet).

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

from pry.core.errors import ExternalServiceError, InvalidRequestError

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


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"crypto_market.{module_name} is not available yet (parallel build in progress)"
    )


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
        _module_unavailable("token_launches")
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
        _module_unavailable("cex_listings")
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
        _module_unavailable("token_security")
    data = await mod.scan_token(chain, address)
    return {"success": True, "data": data}
