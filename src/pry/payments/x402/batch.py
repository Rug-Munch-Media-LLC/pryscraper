"""Pry — x402 batch payment helpers.

Owns the batch payment registry and the create/verify/paid helpers that let
a single x402 payment cover multiple operations. Config constants come from
the package root; scheme/facilitator helpers from their modules.

State backend: Redis (``pry:x402:batch:{batch_id}``) when reachable so batch
state survives across workers; falls back to the in-process dict otherwise
(single-worker only — documented limitation). Consumed tx hashes get the same
treatment (``pry:x402:tx:{network}:{tx_hash}`` via SETNX) so one on-chain tx
can never back both an individual and a batch payment, nor two batches.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import PAYMENT_VALIDITY_SECONDS, X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.facilitator import get_facilitator_router
from pry.payments.x402.scheme import X402_PRICING, _to_atomic, build_payment_required

logger = logging.getLogger(__name__)

# ⚠️ MULTI-WORKER LIMITATION: The in-memory fallback dicts below are per-process.
# Under uvicorn with multiple workers, a batch created in worker A is invisible to
# worker B unless Redis is connected. Production deployments MUST set PRY_REDIS_URL
# to ensure cross-worker batch state consistency. The Redis path is authoritative;
# memory is a last-resort degradation only.

# Active batch payment requests: batch_id -> {operations, total_usd, paid, tx_hash}
# In-memory fallback store (used only when Redis is unreachable).
_batch_payments: dict[str, dict[str, Any]] = {}
_batch_lock = threading.Lock()

# Consumed tx hashes (in-memory fallback for the Redis SETNX replay guard).
_consumed_txs: set[str] = set()


@dataclasses.dataclass
class BatchChannel:
    """On-chain batch settlement channel (voucher/claim/refund model).

    A depositor funds a channel; claims draw it down up to
    ``max_claims_per_batch``; a refund closes the channel and returns the
    remaining balance.
    """

    channel_id: str
    chain_id: str
    depositor: str
    cumulative_claimed: int = 0
    max_claims_per_batch: int = 100
    status: str = "open"


# On-chain batch settlement channels: channel_id -> BatchChannel.
_channels: dict[str, BatchChannel] = {}

# Redis key prefixes + TTL. Batches live slightly longer than their validity
# window so is_batch_paid can still observe the (expired → fail-closed) record.
_BATCH_KEY_PREFIX = "pry:x402:batch:"
_TX_KEY_PREFIX = "pry:x402:tx:"
_BATCH_TTL_SECONDS = PAYMENT_VALIDITY_SECONDS + 60

# Redis connection state (lazy connect + failure cooldown, mirrors ratelimit.py).
_redis_url = ""
_redis_client: Any = None
_redis_failed_at = 0.0
_REDIS_RETRY_SECONDS = 30.0


def _get_redis() -> Any:
    """Return a pinged sync Redis client, or None (with cooldown after failure)."""
    global _redis_url, _redis_client, _redis_failed_at
    if _redis_client is not None:
        return _redis_client
    if not _redis_url:
        try:
            from pry.core.settings import settings

            _redis_url = getattr(settings, "redis_url", "") or ""
        except Exception:  # noqa: BLE001 — settings import must never break payments
            _redis_url = ""
    if not _redis_url:
        return None
    now = time.time()
    if now - _redis_failed_at < _REDIS_RETRY_SECONDS:
        return None
    try:
        import redis as redis_py

        client = redis_py.Redis.from_url(
            _redis_url,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
            decode_responses=True,
        )
        client.ping()
        _redis_client = client
        logger.info("x402_batch_redis_connected")
        return client
    except Exception as e:  # noqa: BLE001 — any backend error must degrade, not raise
        _redis_failed_at = now
        logger.warning(
            "x402_batch_redis_unavailable_falling_back_to_memory",
            extra={"error": str(e)[:160]},
        )
        logger.warning(
            "x402_batch_multi_worker_risk",
            extra={"hint": "Set PRY_REDIS_URL for cross-worker batch consistency"},
        )
        return None


def _batch_redis_key(batch_id: str) -> str:
    return f"{_BATCH_KEY_PREFIX}{batch_id}"


def _tx_redis_key(network: str, tx_hash: str) -> str:
    return f"{_TX_KEY_PREFIX}{network}:{tx_hash}"


def create_channel(chain_id: str, depositor: str) -> BatchChannel:
    """Open a new on-chain batch settlement channel for a depositor."""
    channel_id = hashlib.sha256(f"{chain_id}:{depositor}:{time.time()}".encode()).hexdigest()[:16]
    channel = BatchChannel(channel_id=channel_id, chain_id=chain_id, depositor=depositor)
    with _batch_lock:
        _channels[channel_id] = channel
    return channel


def claim_channel(channel_id: str, amount: int) -> dict[str, Any]:
    """Claim ``amount`` against a channel, respecting the per-batch cap."""
    with _batch_lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return {"success": False, "reason": "Channel not found"}
        if channel.status != "open":
            return {"success": False, "reason": f"Channel is {channel.status}"}
        if channel.cumulative_claimed + amount > channel.max_claims_per_batch:
            return {
                "success": False,
                "reason": "Claim exceeds max_claims_per_batch",
                "cumulative_claimed": channel.cumulative_claimed,
                "max_claims_per_batch": channel.max_claims_per_batch,
            }
        channel.cumulative_claimed += amount
        return {
            "success": True,
            "channel_id": channel_id,
            "cumulative_claimed": channel.cumulative_claimed,
            "remaining": channel.max_claims_per_batch - channel.cumulative_claimed,
        }


def refund_channel(channel_id: str) -> dict[str, Any]:
    """Refund a channel: mark it refunded and return the remaining balance."""
    with _batch_lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return {"success": False, "reason": "Channel not found"}
        if channel.status != "open":
            return {"success": False, "reason": f"Channel is {channel.status}"}
        channel.status = "refunded"
        remaining = channel.max_claims_per_batch - channel.cumulative_claimed
        return {
            "success": True,
            "channel_id": channel_id,
            "status": channel.status,
            "remaining": remaining,
        }


def get_channel(channel_id: str) -> BatchChannel | None:
    """Return a channel by id, or None."""
    with _batch_lock:
        return _channels.get(channel_id)


def _load_batch(batch_id: str) -> dict[str, Any] | None:
    """Load a batch record from Redis, falling back to the in-memory store."""
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(_batch_redis_key(batch_id))
            if raw:
                return json.loads(raw)  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_read_failed", extra={"error": str(e)[:160]})
    with _batch_lock:
        return _batch_payments.get(batch_id)


def _save_batch(batch: dict[str, Any]) -> None:
    """Persist a batch record to Redis (write-through) and the in-memory store."""
    with _batch_lock:
        _batch_payments[batch["batch_id"]] = batch
    client = _get_redis()
    if client is not None:
        try:
            client.set(
                _batch_redis_key(batch["batch_id"]),
                json.dumps(batch),
                ex=_BATCH_TTL_SECONDS,
            )
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_write_failed", extra={"error": str(e)[:160]})


def _consume_tx(tx_hash: str, network: str) -> bool:
    """Atomically claim a tx_hash for a batch payment. True on first claim.

    Replay-hardening: one on-chain tx must not back two payments (batch or
    individual). Redis SETNX makes the claim atomic across workers; the
    in-memory set is the single-worker fallback.
    """
    if not tx_hash:
        return False
    client = _get_redis()
    if client is not None:
        try:
            claimed = client.set(
                _tx_redis_key(network, tx_hash), "1", nx=True, ex=_BATCH_TTL_SECONDS
            )
            return bool(claimed)
        except Exception as e:  # noqa: BLE001 — degrade to memory, never raise
            logger.warning("x402_batch_redis_tx_claim_failed", extra={"error": str(e)[:160]})
    with _batch_lock:
        key = f"{network}:{tx_hash}"
        if key in _consumed_txs:
            return False
        _consumed_txs.add(key)
        return True


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

    _save_batch(
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
    batch = _load_batch(batch_id)
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
    if not _consume_tx(tx_hash, network):
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
    _save_batch(batch)
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
    batch = _load_batch(batch_id)
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
