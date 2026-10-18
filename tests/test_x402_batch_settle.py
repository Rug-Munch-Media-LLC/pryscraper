"""Fail-closed batch settlement (P0): a verified batch is not a settled batch.

The single-payment path already requires a settlement receipt. These tests
pin the same contract on the batch path:

1. ``/v1/x402/batch-verify`` returns ``success: false`` when the batch
   verified but did not settle, and lists the unsettled operations.
2. A settle failure is never reported as success.
3. Per-item receipts are written once per ``(batch_id, operation)``; a
   replayed settle writes nothing (one credit per item).
4. Mixed accounting: one missing receipt makes the whole batch unsettled
   (all-or-nothing gate) and the middleware serves 402.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.payments.x402 import X402Handler
from pry.payments.x402.batch import (
    _batch_lock,
    _batch_payments,
    create_batch_payment,
    state as batch_state,
)
from tests._x402_stage_fakes import (
    _fake_middleware,
    _FakeApp,
    _Recorder,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_batch_state():
    """Deterministic in-memory batch store (Redis forced off)."""
    with _batch_lock:
        _batch_payments.clear()
        batch_state._consumed_txs.clear()
    with patch("pry.payments.x402.batch.store._get_redis", return_value=None):
        yield
    with _batch_lock:
        _batch_payments.clear()
        batch_state._consumed_txs.clear()


def _handler(tmp_path) -> X402Handler:
    return X402Handler(
        payments_file=tmp_path / "payments.jsonl",
        settlements_file=tmp_path / "settlements.jsonl",
    )


async def _batch(operations: list[str]) -> str:
    return (await create_batch_payment(operations))["batch_id"]


def _mark_settled(batch_id: str, tx_hash: str = "0xsettled") -> None:
    with _batch_lock:
        batch = _batch_payments[batch_id]
        batch.update(
            paid=True,
            tx_hash=tx_hash,
            network="base",
            asset="USDC",
            caller_key="10.0.0.9",
            settlement={"success": True, "tx_hash": tx_hash, "network": "base", "asset": "USDC"},
        )


def _receipts(tmp_path) -> list[dict[str, Any]]:
    path = tmp_path / "settlements.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Route: verified != settled
# ---------------------------------------------------------------------------


def _post_verify(batch_id: str, tx_hash: str = "0xabc"):
    return client.post("/v1/x402/batch-verify", json={"batch_id": batch_id, "tx_hash": tx_hash})


def test_verified_but_unsettled_batch_is_not_success():
    with (
        patch(
            "pry.payments.x402.verify_batch_payment",
            _async({"verified": True, "batch_id": "batch_1", "settled": False}),
        ),
        patch.object(
            X402Handler,
            "finalize_batch_settlement",
            return_value={
                "settled": [],
                "unsettled": ["scrape", "monitor"],
                "all_settled": False,
                "written": 0,
            },
        ),
    ):
        response = _post_verify("batch_1")
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["data"]["settled"] is False
    assert body["data"]["unsettled"] == ["scrape", "monitor"]


def test_settle_failure_is_never_success():
    with (
        patch(
            "pry.payments.x402.verify_batch_payment",
            _async(
                {"verified": True, "batch_id": "batch_2", "settled": False, "error": "rpc down"}
            ),
        ),
        patch.object(
            X402Handler,
            "finalize_batch_settlement",
            return_value={
                "settled": [],
                "unsettled": ["scrape"],
                "all_settled": False,
                "written": 0,
            },
        ),
    ):
        body = _post_verify("batch_2").json()
    assert body["success"] is False
    assert body["data"]["settled"] is False
    assert body["data"]["error"] == "rpc down"


def _async(value: Any) -> Any:
    """Tiny awaitable returning ``value`` (no AsyncMock import noise)."""

    async def _call(*_args, **_kwargs):
        return value

    return _call


# ---------------------------------------------------------------------------
# Receipts: one per item, replay writes nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_settle_credits_each_item_once(tmp_path):
    handler = _handler(tmp_path)
    batch_id = await _batch(["scrape", "monitor"])
    _mark_settled(batch_id)

    first = handler.finalize_batch_settlement(batch_id)
    second = handler.finalize_batch_settlement(batch_id)

    assert first["all_settled"] is True
    assert first["written"] == 2
    assert second["all_settled"] is True
    assert second["written"] == 0, "replay must not write a second receipt"
    receipts = _receipts(tmp_path)
    assert len(receipts) == 2
    assert {r["payment_id"] for r in receipts} == {
        f"{batch_id}:scrape",
        f"{batch_id}:monitor",
    }
    assert all(r["reference"].startswith(f"x402:batch:{batch_id}:") for r in receipts)


@pytest.mark.asyncio
async def test_failed_settlement_writes_no_receipt(tmp_path):
    handler = _handler(tmp_path)
    batch_id = await _batch(["scrape"])
    with _batch_lock:
        _batch_payments[batch_id]["settlement"] = {"success": False, "reason": "reverted"}

    status = handler.finalize_batch_settlement(batch_id)

    assert status["all_settled"] is False
    assert status["unsettled"] == ["scrape"]
    assert _receipts(tmp_path) == []


@pytest.mark.asyncio
async def test_mixed_batch_accounting_reports_only_settled_items(tmp_path):
    handler = _handler(tmp_path)
    batch_id = await _batch(["scrape", "monitor"])
    _mark_settled(batch_id)
    handler.record_batch_settlements(
        batch_id,
        ["scrape"],
        {"success": True, "tx_hash": "0xsettled"},
        tx_hash="0xsettled",
        network="base",
    )

    status = handler.batch_settlement_status(batch_id)

    assert status["all_settled"] is False
    assert status["settled"] == ["scrape"]
    assert status["unsettled"] == ["monitor"]


# ---------------------------------------------------------------------------
# Middleware batch stage: all-or-nothing
# ---------------------------------------------------------------------------


class _BatchHandler:
    """Handler stand-in exposing the batch settlement status contract."""

    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status
        self.calls = 0

    def refresh(self) -> None:
        self.calls += 1

    def batch_settlement_status(self, batch_id: str) -> dict[str, Any]:
        return self.status


async def _drive_batch(mw) -> tuple[_Recorder, int | None]:
    recorder = _Recorder()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/scrape",
        "headers": [(b"x-batch-payment-id", b"batch_1")],
        "client": ("10.0.0.9", 1234),
    }
    await mw(scope, None, recorder)
    start = next((f for f in recorder.frames if f["type"] == "http.response.start"), None)
    return recorder, (start or {}).get("status")


@pytest.mark.asyncio
async def test_batch_stage_402_when_any_item_unsettled(monkeypatch):
    handler = _BatchHandler({"settled": ["scrape"], "unsettled": ["monitor"], "all_settled": False})
    mw = _fake_middleware(monkeypatch, app=_FakeApp(), handler=handler, network="base")
    with patch("pry.payments.x402_middleware.enforcement_stages.is_batch_paid", return_value=True):
        _recorder, status = await _drive_batch(mw)
    assert status == 402, "a batch with any unproven item must not be served"
    assert mw.app.calls == []


@pytest.mark.asyncio
async def test_batch_stage_serves_when_every_item_settled(monkeypatch):
    handler = _BatchHandler(
        {"settled": ["scrape", "monitor"], "unsettled": [], "all_settled": True}
    )
    mw = _fake_middleware(monkeypatch, app=_FakeApp(), handler=handler, network="base")
    with patch("pry.payments.x402_middleware.enforcement_stages.is_batch_paid", return_value=True):
        _recorder, status = await _drive_batch(mw)
    assert status == 200
    assert mw.app.calls, "settled batch must be served"
    assert mw.app.calls[0]["x402_verified"]["settled_items"] == ["scrape", "monitor"]
