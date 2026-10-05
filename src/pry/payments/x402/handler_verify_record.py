"""Pry — X402Handler verify replay-guard + record/outcome helpers.

Extracted from ``handler_verify.verify_payment`` (behavior-preserving): the
``_verify_lock``-serialized replay check + payment record, and the
success/failure outcome fan-out (usage tracking, post-verify hooks, failure
hooks). The record body is byte-identical to the inline version.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import PAYMENT_VALIDITY_SECONDS
from pry.payments.x402.metrics import record_replay, record_verify_failure, record_verify_success
from pry.payments.x402.scheme import asset_to_atomic

logger = logging.getLogger(__name__)


def _fail(reason: str) -> dict[str, Any]:
    """Build the canonical unverified verify-result body."""
    return {"verified": False, "reason": reason, "settlement": None}


def fire_verify_failure_hooks(
    handler: Any, payment_id: str, tx_hash: str, network: str, asset: str, reason: str
) -> None:
    """Best-effort on-verify-failure hooks — never break the verify flow."""
    for hook in handler._on_verify_failure_hooks:
        try:
            hook(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                reason=reason,
            )
        except Exception as e:  # noqa: BLE001 — best-effort
            logger.debug(
                "x402_verify_failure_hook_error",
                extra={"payment_id": payment_id, "error": str(e)},
            )


def _build_payment_record(
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
    operation: str,
    result: dict[str, Any],
    caller_key: str,
) -> dict[str, Any]:
    """Assemble the server-authoritative payment record persisted by verify."""
    return {
        "payment_id": payment_id,
        "tx_hash": tx_hash,
        "network": network,
        "asset": asset,
        "amount_usd": amount_usd,
        "required_amount_atomic": asset_to_atomic(amount_usd, asset, network),
        "operation": operation,
        "verified": result["verified"],
        "reason": result.get("reason", ""),
        "facilitator": result.get("facilitator", ""),
        "caller_key": caller_key or "",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)).isoformat(),
        "verified_at": datetime.now(UTC).isoformat(),
    }


def _record_verified_payment(
    handler: Any,
    result: dict[str, Any],
    *,
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
    operation: str,
    caller_key: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Replay-guard + persist under ``_verify_lock``. Returns (abort | None, record)."""
    with handler._verify_lock:
        if result.get("verified") and handler._tx_consumed(tx_hash):
            logger.warning(
                "x402_verify_tx_replay_rejected",
                extra={"payment_id": payment_id, "tx_hash": tx_hash},
            )
            record_replay(network)
            record_verify_failure(network, "tx_hash already consumed")
            return _fail("tx_hash already consumed"), {}
        record = _build_payment_record(
            payment_id, tx_hash, network, asset, amount_usd, operation, result, caller_key
        )
        handler._record_payment(record)
    return None, record


def _apply_verify_outcome(
    handler: Any,
    result: dict[str, Any],
    payment_record: dict[str, Any],
    *,
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
    operation: str,
    caller_key: str,
) -> None:
    """Fan out success (usage + post hooks) or failure (failure hooks)."""
    if result.get("verified"):
        record_verify_success(network)
        handler.usage.record(
            caller_key or payment_id,
            amount_usd=amount_usd,
            endpoint=operation,
            network=network,
        )
        for hook in handler._post_verify_hooks:
            try:
                hook(payment_record)
            except Exception as e:  # noqa: BLE001 — best-effort, never break verify
                logger.debug(
                    "x402_post_verify_hook_error",
                    extra={"payment_id": payment_id, "error": str(e)},
                )
    else:
        record_verify_failure(network, result.get("reason", "verification failed"))
        fire_verify_failure_hooks(
            handler,
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            reason=result.get("reason", "verification failed"),
        )
