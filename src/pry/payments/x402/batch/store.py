"""Redis write-through persistence and transaction replay guard."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import time
from typing import Any

from pry.payments.x402.batch import state
from pry.payments.x402.batch.state import (
    _BATCH_KEY_PREFIX,
    _BATCH_TTL_SECONDS,
    _REDIS_RETRY_SECONDS,
    _TX_KEY_PREFIX,
)

# State values are rebound through the state module by the lazy Redis connector.

logger = logging.getLogger(__name__)


def _get_redis() -> Any:
    """Return a pinged sync Redis client, or None (with cooldown after failure)."""
    if state._redis_client is not None:
        return state._redis_client
    if not state._redis_url:
        try:
            from pry.core.settings import settings

            state._redis_url = getattr(settings, "redis_url", "") or ""
        except Exception:  # noqa: BLE001 — settings import must never break payments
            state._redis_url = ""
    if not state._redis_url:
        return None
    now = time.time()
    if now - state._redis_failed_at < _REDIS_RETRY_SECONDS:
        return None
    try:
        import redis as redis_py

        client = redis_py.Redis.from_url(
            state._redis_url,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
            decode_responses=True,
        )
        client.ping()
        state._redis_client = client
        logger.info("x402_batch_redis_connected")
        return client
    except Exception as e:  # noqa: BLE001 — any backend error must degrade, not raise
        state._redis_failed_at = now
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
    with state._batch_lock:
        return state._batch_payments.get(batch_id)


def _save_batch(batch: dict[str, Any]) -> None:
    """Persist a batch record to Redis (write-through) and the in-memory store."""
    with state._batch_lock:
        state._batch_payments[batch["batch_id"]] = batch
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
    with state._batch_lock:
        key = f"{network}:{tx_hash}"
        if key in state._consumed_txs:
            return False
        state._consumed_txs.add(key)
        return True
