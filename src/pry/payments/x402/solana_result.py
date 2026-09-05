"""Pry — Solana x402 verifier: stable result-shape builders.

The verifier NEVER raises: every RPC error / not-found / malformed response
is converted into ``{"verified": False, "reason": ...}`` so callers can rely
on a stable dict shape. These helpers build that shape.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any


def _failure(reason: str, **extra: Any) -> dict[str, Any]:
    """Build a never-raise failure dict with the stable result shape."""
    result: dict[str, Any] = {
        "verified": False,
        "recipient": "",
        "amount_raw": 0,
        "amount_decimals": 6,
        "amount_usd": 0.0,
        "mint": "",
        "asset": "",
        "confirmed_at": "",
        "reason": reason,
        "slot": None,
    }
    result.update(extra)
    return result


def _success(
    *,
    recipient: str,
    amount_raw: int,
    amount_decimals: int,
    amount_usd: float,
    mint: str,
    confirmed_at: str,
    slot: int | None,
    reason: str = "",
    asset: str = "",
) -> dict[str, Any]:
    return {
        "verified": True,
        "recipient": recipient,
        "amount_raw": amount_raw,
        "amount_decimals": amount_decimals,
        "amount_usd": amount_usd,
        "mint": mint,
        "asset": asset,
        "confirmed_at": confirmed_at,
        "reason": reason,
        "slot": slot,
    }
