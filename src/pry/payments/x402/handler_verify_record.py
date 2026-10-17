"""Pry — X402Handler verify replay-guard + record/outcome helpers.

Extracted from ``handler_verify.verify_payment`` (behavior-preserving): the
``_verify_lock``-serialized replay check + payment record, and the
success/failure outcome fan-out (usage tracking, post-verify hooks, failure
hooks). The replay guard now also consults the SHARED tx-claim namespace used
by the batch path, so one on-chain tx cannot back both payment paths.
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


def _fail(reason: str, code: str = "") -> dict[str, Any]:
    """Build the canonical unverified verify-result body."""
    body: dict[str, Any] = {"verified": False, "reason": reason, "settlement": None}
    if code:
        body["code"] = code
    return body


def _reject_replay(
    network: str, payment_id: str, tx_hash: str, event: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record a cross-path/same-path tx replay and return the fail body."""
    logger.warning(event, extra={"payment_id": payment_id, "tx_hash": tx_hash})
    record_replay(network)
    record_verify_failure(network, "tx_hash already consumed")
    return _fail("tx_hash already consumed", "tx_already_claimed"), {}


def _claim_for_individual(tx_hash: str, network: str) -> bool:
    """Register an individual claim; False only when a BATCH owns the tx.

    The ledger (``_tx_consumed``) remains authoritative for individual-vs-
    individual replay; this guard closes the cross-path (batch → individual)
    hole via the single shared claim namespace.
    """
    from pry.payments.x402.batch.payments import (  # local: avoid import cycle
        CLAIM_BATCH,
        CLAIM_INDIVIDUAL,
        claim_tx,
        tx_claim_owner,
    )

    if not tx_hash:
        return True
    if claim_tx(tx_hash, network, CLAIM_INDIVIDUAL):
        return True
    return tx_claim_owner(tx_hash, network) != CLAIM_BATCH


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
        if result.get("verified"):
            if handler._tx_consumed(tx_hash):
                return _reject_replay(
                    network, payment_id, tx_hash, "x402_verify_tx_replay_rejected"
                )
            # Cross-path replay: an on-chain tx already claimed by a batch.
            if not _claim_for_individual(tx_hash, network):
                return _reject_replay(
                    network, payment_id, tx_hash, "x402_verify_tx_claimed_by_batch"
                )
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
