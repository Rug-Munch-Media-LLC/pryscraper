"""What a payment must cost: asset/amount normalisation and the atomic floor.

Extracted from ``evm_verify`` so the money-critical invariant lives in a small
file that can be read in one pass:

    a request whose price cannot be resolved is REFUSED, never accepted at a
    placeholder.

That guard used to be implicit. ``_resolve_required_atomic`` returned ``1``
atomic unit (0.000001 USDC) for a zero price, and the only thing stopping that
from being a free-endpoint bug was ``handler_verify`` resolving server-side
pricing and failing closed several modules upstream. A price of 1 atom is not a
price; it is the absence of one, and accepting it means paying a millionth of a
cent for any endpoint. The chain that prevents that should not depend on a
caller three modules away continuing to hold it.

Everything here is a pure function of the payment plus the oracle, so it is
cheap to test exhaustively — see ``tests/test_x402_required_atomic_floor.py``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import math
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET
from pry.payments.x402.scheme import normalize_network_id

from .evm_common import _pkg
from .response import VerifyResult

__all__ = [
    "resolve_context",
    "resolve_required_atomic",
]

# Reason returned when no price could be established. Distinct from "no USD
# price for this asset", which is an oracle problem rather than a pricing one.
NO_PRICE = "no server-authoritative price resolved for this payment"


def resolve_context(payment: dict[str, Any]) -> tuple[str, str, float]:
    """Normalize ``(network, asset, amount_usd)`` from the payment dict.

    ``amount_usd`` arrives already resolved from server-side pricing by
    ``handler_verify``, which refuses the request outright when it cannot
    resolve one. This is a second line of defence: an unparseable value becomes
    ``0.0`` here, and :func:`resolve_required_atomic` then refuses rather than
    substituting a placeholder price.
    """
    network = normalize_network_id(str(payment.get("network") or ""))
    asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()
    try:
        amount_usd = float(payment.get("amount_usd") or 0.0)
    except (TypeError, ValueError):
        amount_usd = 0.0
    return network, asset, amount_usd


async def resolve_required_atomic(
    entry: dict[str, Any],
    payment: dict[str, Any],
    asset: str,
    network: str,
    amount_usd: float,
) -> tuple[int | None, VerifyResult | None]:
    """Resolve the required atomic amount (attested first, else live oracle).

    Returns ``(required_atomic, failure)``. Refuses rather than defaulting when
    no price is available, so an unpriced request can never verify.
    """
    decimals = int(entry.get("decimals", 6))
    attested_atomic = 0
    try:
        attested_atomic = int(payment.get("attested_required_atomic") or 0)
    except (TypeError, ValueError):
        attested_atomic = 0
    if attested_atomic > 0:
        return attested_atomic, None
    if not math.isfinite(amount_usd) or amount_usd <= 0:
        return None, VerifyResult(False, NO_PRICE, asset=asset, network=network)
    quote = await _pkg().get_asset_usd_price(asset, network)
    if not quote.usd or quote.usd <= 0:
        return None, VerifyResult(
            False, f"no USD price available for {asset}", asset=asset, network=network
        )
    return round(amount_usd / quote.usd * 10**decimals), None
