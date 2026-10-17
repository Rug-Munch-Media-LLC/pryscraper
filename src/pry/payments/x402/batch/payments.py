"""Batch payment creation, verification, settlement, and access checks."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import PAYMENT_VALIDITY_SECONDS, X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.batch import state as batch_state, store
from pry.payments.x402.facilitator import get_facilitator_router
from pry.payments.x402.metrics import record_replay, record_settle
from pry.payments.x402.scheme import X402_PRICING, _to_atomic, build_payment_required

logger = logging.getLogger(__name__)

# One shared tx-claim namespace for BOTH money paths. ``store`` owns the atomic
# claim (Redis SETNX / in-memory set); the owner tag lets the individual path
# tell a batch claim (must reject) from its own ledger-governed claim.
CLAIM_BATCH = "batch"
CLAIM_INDIVIDUAL = "individual"
_claim_owners: dict[str, str] = {}


def claim_key(tx_hash: str, network: str) -> str:
    """Shared claim key for a tx_hash — identical for batch and individual."""
    return f"{network or X402_DEFAULT_NETWORK}:{tx_hash}"


def claim_tx(tx_hash: str, network: str, owner: str = CLAIM_BATCH) -> bool:
    """Atomically claim ``tx_hash`` in the shared namespace. True on first claim."""
    if not tx_hash:
        return False
    client = store._get_redis()
    if client is not None:
        try:
            claimed = client.set(
                store._tx_redis_key(network, tx_hash),
                owner,
                nx=True,
                ex=batch_state._BATCH_TTL_SECONDS,
            )
            return bool(claimed)
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_tx_claim_failed", extra={"error": str(e)[:160]})
    key = claim_key(tx_hash, network)
    with batch_state._batch_lock:
        if key in batch_state._consumed_txs:
            return False
        batch_state._consumed_txs.add(key)
        _claim_owners[key] = owner
        return True


def tx_claim_owner(tx_hash: str, network: str) -> str:
    """Owner of an existing claim (``batch``/``individual``), '' when unclaimed."""
    if not tx_hash:
        return ""
    client = store._get_redis()
    if client is not None:
        try:
            return str(client.get(store._tx_redis_key(network, tx_hash)) or "")
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_tx_read_failed", extra={"error": str(e)[:160]})
    key = claim_key(tx_hash, network)
    with batch_state._batch_lock:
        if key not in batch_state._consumed_txs:
            _claim_owners.pop(key, None)
            return ""
        return _claim_owners.get(key, CLAIM_BATCH)


def release_tx(tx_hash: str, network: str) -> None:
    """Release a claim after a failed settlement so the batch stays retryable."""
    if not tx_hash:
        return
    client = store._get_redis()
    if client is not None:
        try:
            client.delete(store._tx_redis_key(network, tx_hash))
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_tx_release_failed", extra={"error": str(e)[:160]})
    key = claim_key(tx_hash, network)
    with batch_state._batch_lock:
        batch_state._consumed_txs.discard(key)
        _claim_owners.pop(key, None)


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
    - The tx_hash is claimed once in the SHARED claim namespace (Redis SETNX /
      in-memory set) so a single tx cannot back multiple batch payments or an
      individual one.
    - After a successful verify the payment is settled via the facilitator
      router (verify-only was a security gap: funds were never collected).
    - ``paid`` is set ONLY when settlement succeeds; a failed settle releases
      the claim so the batch stays retryable and never unlocks the gate.
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

    # Replay-hardening: claim the tx atomically before marking paid. The claim
    # namespace is SHARED with the individual verify path, so a tx that already
    # backed an individual payment (or another batch) is refused here.
    if not claim_tx(tx_hash, network, CLAIM_BATCH):
        logger.warning(
            "x402_batch_tx_replay_rejected",
            extra={"batch_id": batch_id, "tx_hash": tx_hash},
        )
        record_replay(network)
        return {
            "verified": False,
            "batch_id": batch_id,
            "reason": "tx_hash already consumed",
            "code": "tx_already_claimed",
            "total_usd": batch["total_usd"],
        }

    # Settle (fix: verify-only batches never collected funds). A failed settle
    # un-consumes the claim and leaves ``paid`` False so the caller can retry.
    settlement: dict[str, Any] = {}
    try:
        settlement = await router.settle(
            batch_id,
            tx_hash,
            network=network,
            asset=asset,
            amount_usd=batch["total_usd"],
        )
    except Exception as e:  # noqa: BLE001 — fail closed on paid, surface settle error
        logger.warning("x402_batch_settle_error", extra={"batch_id": batch_id, "error": str(e)})
        settlement = {"success": False, "reason": f"settle error: {e}"}

    settled = bool(settlement.get("success"))
    record_settle(network, settled, batch["total_usd"], asset)
    if not settled:
        # Never grant paid access on a failed settle, and release the claim so
        # the batch remains retryable with the same tx_hash (do not consume it).
        release_tx(tx_hash, network)
        error = str(settlement.get("reason") or settlement.get("error") or "settlement failed")
        batch["paid"] = False
        batch["tx_hash"] = tx_hash
        batch["network"] = network
        batch["asset"] = asset
        batch["last_error"] = error
        batch["settlement"] = settlement
        batch["settle_attempted_at"] = datetime.now(UTC).isoformat()
        store._save_batch(batch)
        logger.warning(
            "x402_batch_settle_failed_not_paid",
            extra={"batch_id": batch_id, "tx_hash": tx_hash, "error": error},
        )
        return {
            "verified": True,
            "batch_id": batch_id,
            "reason": result.get("reason", ""),
            "total_usd": batch["total_usd"],
            "settled": False,
            "error": error,
        }

    batch["paid"] = True
    batch["tx_hash"] = tx_hash
    batch["network"] = network
    batch["asset"] = asset
    batch["caller_key"] = caller_key or ""
    batch["verified_at"] = datetime.now(UTC).isoformat()
    batch["settlement"] = settlement
    batch.pop("last_error", None)
    store._save_batch(batch)
    return {
        "verified": True,
        "batch_id": batch_id,
        "reason": result.get("reason", ""),
        "total_usd": batch["total_usd"],
        "settled": True,
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
        except ValueError as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "is_batch_paid"},
            )
            return False
    else:
        return False  # no expiry recorded → fail closed
    stored_caller = batch.get("caller_key") or ""
    # Bound batch: only the verifying caller (or an explicitly matching
    # caller_key) may use it — mismatched or missing caller fails closed.
    return not (stored_caller and (not caller_key or stored_caller != caller_key))
