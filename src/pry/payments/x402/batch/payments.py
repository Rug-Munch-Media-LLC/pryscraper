"""Batch payment creation, verification, settlement, and access checks."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import PAYMENT_VALIDITY_SECONDS, X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.batch import store
from pry.payments.x402.facilitator import get_facilitator_router
from pry.payments.x402.scheme import X402_PRICING, _to_atomic, build_payment_required

logger = logging.getLogger(__name__)


async def create_batch_payment(operations: list[str]) -> dict[str, Any]:
    """Create a single x402 payment requirement covering multiple operations.

    Returns a dict with batch_id, total_usd, per-operation breakdown, and a
    spec-compliant PaymentRequired body.
    """
    valid_ops: list[str] = []
    breakdown: list[dict[str, Any]] = []
    total = 0.0
    for op in operations:
        info = X402_PRICING.get(op)
        if not info:
            continue
        valid_ops.append(op)
        price = info["price_usd"]
        total += price
        breakdown.append({"operation": op, "price_usd": price})

    if not valid_ops:
        return {"error": "No valid operations provided"}

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    payment_required = build_payment_required(
        operation=valid_ops[0],
        resource=f"https://pry.dev/api/batch?ops={','.join(valid_ops)}",
        description=f"Batch payment for {len(valid_ops)} operations",
    )
    # Override the accepts amount to the batch total
    for acceptance in payment_required.get("accepts", []):
        asset = acceptance.get("asset", X402_DEFAULT_ASSET)
        acceptance["maxAmountRequired"] = str(_to_atomic(total, asset))
        acceptance["description"] = f"Batch: {', '.join(valid_ops)}"
        acceptance["extra"]["batch_id"] = batch_id
        acceptance["extra"]["operations"] = valid_ops

    store._save_batch(
        {
            "batch_id": batch_id,
            "operations": valid_ops,
            "total_usd": round(total, 6),
            "paid": False,
            "tx_hash": "",
            "caller_key": "",
            "payment_required": payment_required,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (
                datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)
            ).isoformat(),
        }
    )

    return {
        "batch_id": batch_id,
        "total_usd": round(total, 6),
        "operations": breakdown,
        "payment_required": payment_required,
    }


async def verify_batch_payment(
    batch_id: str,
    tx_hash: str,
    network: str = "",
    asset: str = "",
    caller_key: str = "",
) -> dict[str, Any]:
    """Verify a batch payment on-chain, settle it, and mark it paid if valid.

    Hardening:
    - ``caller_key`` (IP/payer identity) is bound to the batch at verify time
      so ``is_batch_paid`` can reject replay from a different caller.
    - The tx_hash is atomically claimed once (Redis SETNX / in-memory set) so
      a single tx cannot back multiple batch payments or an individual one.
    - After a successful verify the payment is settled via the facilitator
      router (verify-only was a security gap: funds were never collected).
    """
    network = network or X402_DEFAULT_NETWORK
    asset = asset or X402_DEFAULT_ASSET
    batch = store._load_batch(batch_id)
    if not batch:
        return {"verified": False, "reason": "Batch not found"}
    if batch.get("paid"):
        return {"verified": True, "batch_id": batch_id, "note": "Already paid"}

    router = get_facilitator_router()
    result = await router.verify(
        batch_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=batch["total_usd"],
    )
    if not result["verified"]:
        return {
            "verified": False,
            "batch_id": batch_id,
            "reason": result.get("reason", ""),
            "total_usd": batch["total_usd"],
        }

    # Replay-hardening: claim the tx atomically before marking paid. A tx that
    # already backed an individual payment (or another batch) is refused here.
    if not store._consume_tx(tx_hash, network):
        logger.warning(
            "x402_batch_tx_replay_rejected",
            extra={"batch_id": batch_id, "tx_hash": tx_hash},
        )
        return {
            "verified": False,
            "batch_id": batch_id,
            "reason": "tx_hash already consumed",
            "total_usd": batch["total_usd"],
        }

    # Settle (fix: verify-only batches never collected funds). A failed settle
    # does not un-verify the batch — the settlement can be retried — but it is
    # surfaced in the response so the caller knows funds are not yet collected.
    settlement: dict[str, Any] = {}
    try:
        settlement = await router.settle(
            batch_id,
            tx_hash,
            network=network,
            asset=asset,
            amount_usd=batch["total_usd"],
        )
    except Exception as e:  # noqa: BLE001 — fail open on verify, surface settle error
        logger.warning("x402_batch_settle_error", extra={"batch_id": batch_id, "error": str(e)})
        settlement = {"success": False, "reason": f"settle error: {e}"}

    batch["paid"] = True
    batch["tx_hash"] = tx_hash
    batch["network"] = network
    batch["asset"] = asset
    batch["caller_key"] = caller_key or ""
    batch["verified_at"] = datetime.now(UTC).isoformat()
    batch["settlement"] = settlement
    store._save_batch(batch)
    return {
        "verified": True,
        "batch_id": batch_id,
        "reason": result.get("reason", ""),
        "total_usd": batch["total_usd"],
        "settled": bool(settlement.get("success")),
    }


def is_batch_paid(batch_id: str, caller_key: str = "", operation: str = "") -> bool:
    """Check whether a batch payment has been verified and is still valid.

    Batch payments expire after PAYMENT_VALIDITY_SECONDS; expired batches
    fail closed (client must create a new batch payment). When the batch was
    bound to a ``caller_key`` at verify time, only that caller may use it —
    a mismatched or missing caller fails closed (replay hardening). When an
    ``operation`` is supplied, the batch must cover that operation — a batch
    that does not list it fails closed (operation gating).
    """
    batch = store._load_batch(batch_id)
    if not batch or not batch.get("paid"):
        return False
    if operation and operation not in batch.get("operations", []):
        return False
    expires_at = batch.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
                return False
        except ValueError:
            return False
    else:
        return False  # no expiry recorded → fail closed
    stored_caller = batch.get("caller_key") or ""
    # Bound batch: only the verifying caller (or an explicitly matching
    # caller_key) may use it — mismatched or missing caller fails closed.
    return not (stored_caller and (not caller_key or stored_caller != caller_key))
