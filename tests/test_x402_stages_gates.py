# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the split x402 enforcement stages.

Payment-critical: these cover the early-stage helpers extracted from
``X402Middleware.__call__`` (``enforcement_stages``) and the pure checks plus
verify→settle orchestration in ``enforcement_payment_checks`` /
``enforcement_payment``. No network, no facilitator, no Redis — collaborators
are injected fakes. The ordering assertions are the point: verify must be
consulted before settle, and settle must have happened before serving.
"""

from __future__ import annotations

from typing import Any

from pry.payments.x402_middleware import (
    enforcement_stages as stages,
)
from tests._x402_stage_fakes import _FakeHandler, _FakeMW, _Recorder


class TestBypassGate:
    """Non-HTTP / preflight / owner / internal / free bypass the gate."""

    async def test_non_http_scope_is_served(self):
        mw = _FakeMW()
        recorder = _Recorder()
        scope = {"type": "lifespan"}
        assert await stages._bypass_gate(mw, scope, None, recorder) is True
        expected = [{"type": "lifespan"}]
        assert mw.app.calls == expected

    async def test_options_preflight_is_served(self):
        mw = _FakeMW()
        recorder = _Recorder()
        scope = {"type": "http", "method": "OPTIONS", "path": "/v1/scrape", "headers": []}
        assert await stages._bypass_gate(mw, scope, None, recorder) is True
        assert mw.app.calls

    async def test_free_path_is_served(self):
        mw = _FakeMW()
        mw._free = True
        recorder = _Recorder()
        scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}
        assert await stages._bypass_gate(mw, scope, None, recorder) is True

    async def test_paid_path_without_credential_is_not_bypassed(self):
        mw = _FakeMW()
        recorder = _Recorder()
        scope = {"type": "http", "method": "GET", "path": "/v1/scrape", "headers": []}
        assert await stages._bypass_gate(mw, scope, None, recorder) is False
        assert mw.app.calls == []


class TestPreverifiedPaymentStage:
    """A stored valid payment is served and stamped; otherwise it declines."""

    async def test_missing_header_declines(self):
        mw = _FakeMW()
        recorder = _Recorder()
        served = await stages._serve_preverified_payment(
            mw, {}, None, recorder, "", "caller", "scrape"
        )
        assert served is False
        assert mw.app.calls == []

    async def test_valid_payment_refreshes_then_serves_and_stamps(self):
        handler = _FakeHandler(paid=True)
        handler.batch_settlement_status = lambda *a, **k: {
            "settled": ["scrape"], "unsettled": [], "all_settled": True
        }
        # P0: verified is not settled — the gate now also requires a receipt.
        handler._settled_txs = {"tx:base:0xabc": {"success": True, "payment_id": "pay_1"}}
        mw = _FakeMW(handler=handler)
        recorder = _Recorder()
        scope: dict[str, Any] = {}
        served = await stages._serve_preverified_payment(
            mw, scope, None, recorder, "pay_1", "caller", "scrape"
        )
        assert served is True
        assert handler.calls[0] == "refresh", "refresh must precede the is_paid check"
        assert scope["x402_verified"]["payment_id"] == "pay_1"
        assert scope["x402_verified"]["operation"] == "scrape"
        assert mw.app.calls

    async def test_unpaid_payment_declines(self):
        mw = _FakeMW(handler=_FakeHandler(paid=False))
        recorder = _Recorder()
        served = await stages._serve_preverified_payment(
            mw, {}, None, recorder, "pay_1", "caller", "scrape"
        )
        assert served is False
        assert mw.app.calls == []


class TestPreverifiedBatchStage:
    """Batch payments consult is_batch_paid and stamp x402_verified."""

    async def test_missing_batch_header_declines(self):
        mw = _FakeMW()
        recorder = _Recorder()
        assert (
            await stages._serve_preverified_batch(mw, {}, None, recorder, "", "caller", "scrape")
            is False
        )

    async def test_paid_batch_is_served_and_stamped(self, monkeypatch):
        monkeypatch.setattr(stages, "is_batch_paid", lambda *a, **k: True)
        # P0: verified is not settled — the batch gate now also needs receipts.
        monkeypatch.setattr(
            stages, "_batch_settlement_status",
            lambda *a, **k: {"settled": ["scrape"], "unsettled": [], "all_settled": True},
        )
        mw = _FakeMW()
        recorder = _Recorder()
        scope: dict[str, Any] = {}
        served = await stages._serve_preverified_batch(
            mw, scope, None, recorder, "batch_1", "caller", "scrape"
        )
        assert served is True
        assert scope["x402_verified"]["batch_id"] == "batch_1"

    async def test_unpaid_batch_declines(self, monkeypatch):
        monkeypatch.setattr(stages, "is_batch_paid", lambda *a, **k: False)
        mw = _FakeMW()
        recorder = _Recorder()
        assert (
            await stages._serve_preverified_batch(
                mw, {}, None, recorder, "batch_1", "caller", "scrape"
            )
            is False
        )
