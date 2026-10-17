"""Branch coverage for batch payment claims, settle failure and paid gating."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from pry.payments.x402.batch import payments as bp, state as batch_state, store as batch_store


@pytest.fixture(autouse=True)
def _clean_claims():
    batch_state._consumed_txs.clear()
    bp._claim_owners.clear()
    yield
    batch_state._consumed_txs.clear()
    bp._claim_owners.clear()


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.down: set[str] = set()

    def set(self, key, value, nx=False, ex=None):
        if "set" in self.down:
            raise RuntimeError("redis set down")
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def get(self, key):
        if "get" in self.down:
            raise RuntimeError("redis get down")
        return self.data.get(key)

    def delete(self, key):
        if "delete" in self.down:
            raise RuntimeError("redis delete down")
        self.data.pop(key, None)


def test_claim_tx_redis_claim_conflict_and_release(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(batch_store, "_get_redis", lambda: redis)

    assert bp.claim_tx("", "base") is False
    assert bp.claim_tx("0xa", "base") is True
    assert bp.claim_tx("0xa", "base") is False
    assert bp.tx_claim_owner("0xa", "base") == "batch"
    bp.release_tx("0xa", "base")
    assert bp.tx_claim_owner("0xa", "base") == ""
    assert bp.claim_tx("0xa", "base") is True


def test_claim_tx_redis_outage_degrades_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    redis.down.update({"set", "get", "delete"})
    monkeypatch.setattr(batch_store, "_get_redis", lambda: redis)

    assert bp.claim_tx("0xb", "base") is True
    assert bp.tx_claim_owner("0xb", "base") == "batch"
    bp.release_tx("0xb", "base")
    assert bp.tx_claim_owner("0xb", "base") == ""
    assert bp.tx_claim_owner("", "base") == ""


def test_claim_conflict_returns_replay_code(monkeypatch: pytest.MonkeyPatch) -> None:
    replays: list[str] = []
    monkeypatch.setattr(bp, "claim_tx", lambda *_a, **_k: False)
    monkeypatch.setattr(bp, "record_replay", lambda network: replays.append(network))

    out = bp._claim_or_reject("0xa", "base", "batch_1", 1.5)

    assert out == {
        "verified": False,
        "batch_id": "batch_1",
        "reason": "tx_hash already consumed",
        "code": "tx_already_claimed",
        "total_usd": 1.5,
    }
    assert replays == ["base"]


class _Router:
    def __init__(self, settle_result):
        self.settle_result = settle_result
        self.verified = 0

    async def verify(self, *_a, **_k):
        self.verified += 1
        return {"verified": True, "reason": "onchain"}

    async def settle(self, *_a, **_k):
        if isinstance(self.settle_result, Exception):
            raise self.settle_result
        return self.settle_result


def test_settle_failure_releases_claim_and_keeps_unpaid(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = {"batch_id": "b1", "total_usd": 2.0, "paid": False, "operations": ["scrape"]}
    saved: list[dict] = []
    released: list[tuple] = []
    monkeypatch.setattr(bp.store, "_load_batch", lambda _bid: batch)
    monkeypatch.setattr(bp.store, "_save_batch", saved.append)
    monkeypatch.setattr(
        bp, "get_facilitator_router", lambda: _Router({"success": False, "reason": "declined"})
    )
    monkeypatch.setattr(bp, "claim_tx", lambda *_a, **_k: True)
    monkeypatch.setattr(bp, "release_tx", lambda tx, net: released.append((tx, net)))

    out = asyncio.run(bp.verify_batch_payment("b1", "0xh", network="base"))

    assert out["settled"] is False
    assert out["error"] == "declined"
    assert out["verified"] is True
    assert released == [("0xh", "base")]
    assert saved[-1]["paid"] is False
    assert saved[-1]["last_error"] == "declined"


def test_settle_exception_is_surfaced_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = {"batch_id": "b2", "total_usd": 1.0, "paid": False, "operations": ["scrape"]}
    monkeypatch.setattr(bp.store, "_load_batch", lambda _bid: batch)
    monkeypatch.setattr(bp.store, "_save_batch", lambda _b: None)
    monkeypatch.setattr(bp, "get_facilitator_router", lambda: _Router(RuntimeError("boom")))
    monkeypatch.setattr(bp, "claim_tx", lambda *_a, **_k: True)
    monkeypatch.setattr(bp, "release_tx", lambda *_a: None)

    out = asyncio.run(bp.verify_batch_payment("b2", "0xi", network="base"))
    assert out["error"] == "settle error: boom"


def test_is_batch_paid_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    future = (now + timedelta(minutes=5)).isoformat()
    past = (now - timedelta(minutes=5)).isoformat()
    batches = {
        "noexp": {"paid": True, "operations": ["scrape"], "expires_at": ""},
        "expired": {"paid": True, "operations": ["scrape"], "expires_at": past},
        "bad": {"paid": True, "operations": ["scrape"], "expires_at": "nope"},
        "bound": {"paid": True, "operations": ["scrape"], "expires_at": future, "caller_key": "k1"},
        "opmiss": {"paid": True, "operations": ["scrape"], "expires_at": future},
        "unpaid": {"paid": False, "operations": ["scrape"], "expires_at": future},
    }
    monkeypatch.setattr(bp.store, "_load_batch", lambda bid: batches.get(bid))

    assert bp.is_batch_paid("noexp") is False
    assert bp.is_batch_paid("expired") is False
    assert bp.is_batch_paid("bad") is False
    assert bp.is_batch_paid("bound", caller_key="") is False
    assert bp.is_batch_paid("bound", caller_key="k2") is False
    assert bp.is_batch_paid("bound", caller_key="k1") is True
    assert bp.is_batch_paid("opmiss", operation="crawl") is False
    assert bp.is_batch_paid("unpaid") is False
    assert bp.is_batch_paid("missing") is False


def test_claim_owner_memory_path_and_empty_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_store, "_get_redis", lambda: None)

    assert bp.claim_tx("0xc", "base") is True
    assert bp.tx_claim_owner("0xc", "base") == "batch"
    assert bp.release_tx("", "base") is None
    assert bp.tx_claim_owner("0xc", "base") == "batch"
