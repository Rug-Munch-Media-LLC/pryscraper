# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402/batch.py — batch payment registry and helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from pry.payments.x402 import batch as batch_mod
from pry.payments.x402.batch import (
    _batch_lock,
    _batch_payments,
    _consumed_txs,
    create_batch_payment,
    is_batch_paid,
    verify_batch_payment,
)

store = batch_mod.store


@pytest.fixture(autouse=True)
def clear_batch_registry():
    """Clear the in-memory batch registry and tx-replay set before each test.

    Redis is forced off so tests exercise the deterministic in-memory fallback
    path (a live Redis on the dev box must not change test behavior).
    """
    with _batch_lock:
        _batch_payments.clear()
        _consumed_txs.clear()
    with patch.object(store, "_get_redis", return_value=None):
        yield
    with _batch_lock:
        _batch_payments.clear()
        _consumed_txs.clear()


# create_batch_payment


@pytest.mark.asyncio
async def test_create_single_op():
    result = await create_batch_payment(["scrape"])
    assert "batch_id" in result
    assert result["total_usd"] > 0
    assert len(result["operations"]) == 1
    assert "payment_required" in result


@pytest.mark.asyncio
async def test_create_multiple_ops():
    result = await create_batch_payment(["scrape", "monitor"])
    assert [op["operation"] for op in result["operations"]] == ["scrape", "monitor"]
    assert result["total_usd"] == pytest.approx(0.021)


@pytest.mark.asyncio
async def test_create_all_ops():
    result = await create_batch_payment(
        [
            "scrape",
            "crawl",
            "extract",
            "monitor",
            "llm_call",
            "bulk_crawl",
        ]
    )
    assert [op["operation"] for op in result["operations"]] == [
        "scrape",
        "crawl",
        "extract",
        "monitor",
        "llm_call",
        "bulk_crawl",
    ]
    assert result["total_usd"] == pytest.approx(sum(op["price_usd"] for op in result["operations"]))


@pytest.mark.asyncio
async def test_create_unknown_op():
    assert "error" in await create_batch_payment(["unknown_op"])


@pytest.mark.asyncio
async def test_create_all_unknown():
    assert "error" in await create_batch_payment(["op1", "op2"])


@pytest.mark.asyncio
async def test_create_empty():
    assert "error" in await create_batch_payment([])


@pytest.mark.asyncio
async def test_create_has_pricing():
    ops = (await create_batch_payment(["scrape", "monitor"]))["operations"]
    assert {op["operation"]: op["price_usd"] for op in ops} == {
        "scrape": 0.001,
        "monitor": 0.02,
    }


@pytest.mark.asyncio
async def test_create_id_format():
    bid = (await create_batch_payment(["scrape"]))["batch_id"]
    assert bid.startswith("batch_")
    assert len(bid) > 10


# ---------------------------------------------------------------------------
# verify_batch_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_not_found():
    r = await verify_batch_payment("nonexistent", "0xdead")
    assert r["verified"] is False
    assert "not found" in r.get("reason", "").lower()


@pytest.mark.asyncio
async def test_verify_already_paid():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["tx_hash"] = "0xpaid"

    r2 = await verify_batch_payment(bid, "0xpaid")
    assert r2["verified"] is True
    assert "already paid" in r2.get("note", "").lower()


@pytest.mark.asyncio
async def test_verify_onchain_success():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xvalid")
        assert r2["verified"] is True
        assert r2["total_usd"] > 0


@pytest.mark.asyncio
async def test_verify_onchain_failure():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": False, "reason": "insufficient"}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xinvalid")
        assert r2["verified"] is False


# ---------------------------------------------------------------------------
# is_batch_paid
# ---------------------------------------------------------------------------


def test_is_paid_no_such():
    assert is_batch_paid("no_such") is False


@pytest.mark.asyncio
async def test_is_paid_unpaid():
    r = await create_batch_payment(["scrape"])
    assert is_batch_paid(r["batch_id"]) is False


@pytest.mark.asyncio
async def test_is_paid_yes():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
    assert is_batch_paid(bid) is True


@pytest.mark.asyncio
async def test_is_paid_expired():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    assert is_batch_paid(bid) is False


@pytest.mark.asyncio
async def test_is_paid_bad_expiry():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["expires_at"] = "bad-date"
    assert is_batch_paid(bid) is False


@pytest.mark.asyncio
async def test_is_paid_no_expiry():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid].pop("expires_at", None)
    # Fail closed: a paid record without an expiry must never grant access.
    assert is_batch_paid(bid) is False


# ---------------------------------------------------------------------------
# Settlement (fix #1: verify-only batches never collected funds)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_settles_after_verify():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.return_value = {"success": True}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xvalid")
        assert r2["verified"] is True
        assert r2["settled"] is True
        mock.settle.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_settle_failure_does_not_unverify():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.return_value = {"success": False, "reason": "rpc down"}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xvalid")
        assert r2["verified"] is True
        assert r2["settled"] is False
    assert is_batch_paid(bid) is True


@pytest.mark.asyncio
async def test_verify_settle_exception_surfaced():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.side_effect = RuntimeError("boom")

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xvalid")
        assert r2["verified"] is True
        assert r2["settled"] is False


# ---------------------------------------------------------------------------
# Caller binding (fix #2: replayable cross-IP until expiry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_caller_binding_blocks_other_caller():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.return_value = {"success": True}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        await verify_batch_payment(bid, "0xvalid", caller_key="1.2.3.4")
    assert is_batch_paid(bid, caller_key="1.2.3.4") is True
    # Different caller → rejected
    assert is_batch_paid(bid, caller_key="5.6.7.8") is False
    # Missing caller → fail closed
    assert is_batch_paid(bid) is False


@pytest.mark.asyncio
async def test_unbound_batch_legacy_contract():
    """Batches verified without a caller_key stay usable by any caller."""
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.return_value = {"success": True}

    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        await verify_batch_payment(bid, "0xvalid")
    assert is_batch_paid(bid) is True


# ---------------------------------------------------------------------------
# Tx replay (fix #4: one tx must not back two payments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tx_replay_second_batch_rejected():
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}
    mock.settle.return_value = {"success": True}

    r1 = await create_batch_payment(["scrape"])
    r2 = await create_batch_payment(["monitor"])
    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
        first = await verify_batch_payment(r1["batch_id"], "0xsametx")
        second = await verify_batch_payment(r2["batch_id"], "0xsametx")
    assert first["verified"] is True
    assert second["verified"] is False
    assert "already consumed" in second["reason"]


@pytest.mark.asyncio
async def test_tx_replay_redis_setnx_semantics():
    """The in-memory fallback must behave like Redis SETNX: first claim wins."""
    assert store._consume_tx("0xabc", "base") is True
    assert store._consume_tx("0xabc", "base") is False
    assert store._consume_tx("0xabc", "polygon") is True  # different network → distinct tx
    assert store._consume_tx("", "base") is False  # empty hash never claims


class _FakeRedis:
    """Minimal sync-Redis stub implementing get/set(nx)/ping for batch state."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


@pytest.mark.asyncio
async def test_redis_backend_roundtrip_and_replay():
    """Batch state round-trips through Redis and SETNX blocks cross-worker replay."""
    fake = _FakeRedis()
    with patch.object(store, "_get_redis", return_value=fake):
        r = await create_batch_payment(["scrape"])
        bid = r["batch_id"]
        assert f"pry:x402:batch:{bid}" in fake.store  # write-through to Redis

        mock = AsyncMock()
        mock.verify.return_value = {"verified": True, "reason": ""}
        mock.settle.return_value = {"success": True}

        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
            r2 = await verify_batch_payment(bid, "0xredis", caller_key="9.9.9.9")
            assert r2["verified"] is True
        # A second worker (fresh in-memory state, same Redis) sees the paid batch.
        with _batch_lock:
            _batch_payments.clear()
            _consumed_txs.clear()
        assert is_batch_paid(bid, caller_key="9.9.9.9") is True
        # And the tx claim survives: a second batch on the same tx is refused.
        r3 = await create_batch_payment(["monitor"])
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
            third = await verify_batch_payment(r3["batch_id"], "0xredis")
        assert third["verified"] is False


# ---------------------------------------------------------------------------
# Redis failure degradation (Redis down mid-flight → in-memory fallback)
# ---------------------------------------------------------------------------


class _BrokenRedis:
    """A Redis client that was reachable at connect time but now errors."""

    def get(self, key: str) -> str:
        raise ConnectionError("redis down")

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_redis_down_falls_back_to_memory():
    """With a reachable-but-broken Redis, batch state degrades to memory and
    the full create → verify → is_paid flow still works (never raises)."""
    with patch.object(store, "_get_redis", return_value=_BrokenRedis()):
        r = await create_batch_payment(["scrape", "monitor"])
        bid = r["batch_id"]
        assert r["total_usd"] > 0

        mock = AsyncMock()
        mock.verify.return_value = {"verified": True, "reason": ""}
        mock.settle.return_value = {"success": True}
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=mock):
            result = await verify_batch_payment(bid, "0xdegraded", caller_key="c1")
        assert result["verified"] is True

        # State survived in the in-memory fallback store.
        assert is_batch_paid(bid, caller_key="c1") is True
        # Replay hardening still enforced from memory.
        assert is_batch_paid(bid, caller_key="other") is False


@pytest.mark.asyncio
async def test_redis_tx_claim_failure_falls_back_to_memory_set():
    """When the Redis SETNX claim errors, the in-memory tx set still blocks replay."""
    with patch.object(store, "_get_redis", return_value=_BrokenRedis()):
        assert store._consume_tx("0xtx1", "eip155:8453") is True
        assert store._consume_tx("0xtx1", "eip155:8453") is False  # replay blocked
        assert store._consume_tx("0xtx2", "eip155:8453") is True
        assert store._consume_tx("", "eip155:8453") is False  # empty hash refused


@pytest.mark.asyncio
async def test_redis_read_failure_serves_memory_record():
    """A batch saved to memory is still loadable when Redis reads fail."""
    bid = (await create_batch_payment(["scrape"]))["batch_id"]
    with patch.object(store, "_get_redis", return_value=_BrokenRedis()):
        loaded = store._load_batch(bid)
        assert loaded is not None
        assert loaded["batch_id"] == bid
