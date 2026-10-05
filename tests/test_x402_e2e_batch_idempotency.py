# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end x402 batch settlement idempotency (replay guard).

A batch's on-chain tx_hash must back exactly one batch: the first verify that
claims it settles, and a second batch presenting the same tx is refused before
any second settlement. This is the batch-side counterpart to the single-payment
replay guard in ``test_x402_e2e_failures_batch.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pry.payments.x402.batch import state, verify_batch_payment
from pry.payments.x402.batch.payments import create_batch_payment

CALLER = "10.0.0.7"


@pytest.fixture(autouse=True)
def _clear_state():
    """Isolate the in-memory batch + tx registries; Redis forced off."""
    from pry.payments.x402.batch import store

    with state._batch_lock:
        state._batch_payments.clear()
        state._consumed_txs.clear()
    with patch.object(store, "_get_redis", return_value=None):
        yield
    with state._batch_lock:
        state._batch_payments.clear()
        state._consumed_txs.clear()


def _router(*, settle_ok: bool = True) -> AsyncMock:
    router = AsyncMock()
    router.verify.return_value = {"verified": True, "reason": ""}
    router.settle.return_value = {"success": settle_ok}
    return router


class TestBatchIdempotency:
    async def test_same_tx_cannot_back_two_batches(self):
        """First batch settles; the second presenting the same tx is refused."""
        router = _router()
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
            b1 = (await create_batch_payment(["scrape"]))["batch_id"]
            b2 = (await create_batch_payment(["monitor"]))["batch_id"]
            first = await verify_batch_payment(b1, "0xsame", caller_key=CALLER)
            second = await verify_batch_payment(b2, "0xsame", caller_key=CALLER)
        assert first["verified"] is True
        assert second["verified"] is False
        assert "already consumed" in second["reason"]
        assert router.settle.await_count == 1, "replay must not settle a second time"

    async def test_reverify_paid_batch_is_idempotent(self):
        """Re-verifying an already-paid batch returns the paid note, no re-settle."""
        router = _router()
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
            bid = (await create_batch_payment(["scrape"]))["batch_id"]
            first = await verify_batch_payment(bid, "0xonce", caller_key=CALLER)
            again = await verify_batch_payment(bid, "0xonce", caller_key=CALLER)
        assert first["verified"] is True
        assert again["verified"] is True
        assert again.get("note") == "Already paid"
        assert router.settle.await_count == 1


class TestBatchPartialFailure:
    async def test_settle_failure_still_verifies_but_surfaces_unsettled(self):
        """Verify ok + settle fail: verified=True, settled=False (retryable)."""
        router = _router(settle_ok=False)
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
            bid = (await create_batch_payment(["scrape"]))["batch_id"]
            result = await verify_batch_payment(bid, "0xfail", caller_key=CALLER)
        assert result["verified"] is True
        assert result["settled"] is False

    async def test_verify_failure_does_not_consume_tx(self):
        """A failed on-chain verify leaves the tx unclaimed for a later retry."""
        router = AsyncMock()
        router.verify.return_value = {"verified": False, "reason": "not found"}
        with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
            bid = (await create_batch_payment(["scrape"]))["batch_id"]
            result = await verify_batch_payment(bid, "0xretry", caller_key=CALLER)
        assert result["verified"] is False
        with state._batch_lock:
            assert "base:0xretry" not in state._consumed_txs
