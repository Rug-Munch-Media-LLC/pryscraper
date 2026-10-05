"""Pry — X402Handler verify pre-gates (pure helpers).

Extracted from ``handler_verify.verify_payment`` (behavior-preserving): the
pre-verify hook fan-out, the server-authoritative pricing resolution and the
fail-closed "no server price" refusal. Every helper returns either
``(None, None)`` (proceed) or ``(result_dict, amount_usd)`` where ``result``
is the terminal ``{"verified": False, ...}`` body to return.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from pry.payments.x402.metrics import record_verify_failure
from pry.payments.x402.scheme import X402_PRICING, resolve_price_usd, validate_client_amount

logger = logging.getLogger(__name__)


def _fail(reason: str) -> dict[str, Any]:
    """Build the canonical unverified verify-result body."""
    return {"verified": False, "reason": reason, "settlement": None}


def _run_pre_verify_hooks(
    handler: Any, payment_id: str, tx_hash: str, network: str, asset: str, amount_usd: float
) -> dict[str, Any] | None:
    """Run registered pre-verify hooks; return an abort body or None to proceed."""
    for hook in handler._pre_verify_hooks:
        result = hook(
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
        )
        if isinstance(result, dict) and result.get("abort"):
            logger.info(
                "x402_verify_aborted_by_pre_verify_hook",
                extra={"payment_id": payment_id, "reason": result.get("reason", "")},
            )
            return _fail(result.get("reason", "aborted by pre-verify hook"))
    return None


def _resolve_server_amount(
    operation: str, amount_usd: float, asset: str, network: str
) -> tuple[dict | None, float]:
    """Validate + resolve the authoritative price. Returns (abort body | None, amount)."""
    if not operation:
        return None, amount_usd
    ok, reason = validate_client_amount(operation, amount_usd, asset, network=network)
    if not ok:
        logger.warning(
            "x402_verify_underpayment_rejected",
            extra={"operation": operation, "reason": reason},
        )
        return _fail(reason), amount_usd
    record_verify_failure(network, reason)
    return None, resolve_price_usd(operation, network=network, asset=asset)


def _resolve_fallback_amount(
    payment_id: str, operation: str, amount_usd: float, network: str
) -> tuple[dict | None, float]:
    """Fail closed when no server-authoritative price is resolvable."""
    if amount_usd > 0:
        return None, amount_usd
    amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.0)
    if amount_usd <= 0:
        logger.warning(
            "x402_verify_pricing_unavailable",
            extra={"operation": operation, "payment_id": payment_id},
        )
        return _fail("unknown operation: pricing unavailable"), amount_usd
    record_verify_failure(network, "unknown operation: pricing unavailable")
    return None, amount_usd
