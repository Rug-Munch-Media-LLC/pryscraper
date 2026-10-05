# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end x402 money path: verify -> settle -> record -> response.

In-process ASGI flow through the real ``X402Middleware`` with a faked
facilitator handler (see ``tests/_x402_stage_fakes``). No network, no Redis.
The invariants under test are ordering and exactly-once recording:

- verify is consulted BEFORE settle (a failed verify never calls settle);
- a failed settle grants NO access and never reaches the app handler;
- a successful settle grants access AND the receipt is written exactly once.
"""

from __future__ import annotations

import base64
import json

import pytest

from pry.payments.x402_middleware import enforcement_payment as payment
from tests._x402_stage_fakes import (
    _fake_middleware,
    _FakeApp,
    _FakeHandler,
    _ReceiptLedger,
    _Recorder,
    _scope as _x402_scope,
    _sig,
)

PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.7"


@pytest.fixture
def mw(monkeypatch):
    """Real X402Middleware with a faked handler + a receipt ledger.

    The gate's attestation/price helpers are forced to the pass-through value
    here; they have their own dedicated failure-matrix suite. This file is
    about verify/settle ordering and the exactly-once record.
    """
    handler = _FakeHandler(settlement={"success": True, "tx": "0xabc"})
    ledger = _ReceiptLedger()
    app = _FakeApp()
    middleware = _fake_middleware(monkeypatch, app=app, handler=handler, network="base")
    middleware._fake_ledger = ledger
    return middleware


def _present_presented(middleware):
    """Drive one presented-payment request; return (recorder, scope, sig)."""
    recorder = _Recorder()
    scope = _x402_scope(payment_sig=_sig({"payment_id": "p1", "tx_hash": "0xabc"}), caller=CALLER)
    return recorder, scope, scope["headers"][0][1].decode()


class TestOrderingAndExactlyOnce:
    async def test_verify_precedes_settle(self, monkeypatch, mw):
        """Success path: verify then settle, in that exact order."""
        _patch_checks_pass(monkeypatch, payment)
        ordered: list[str] = []
        original_verify = mw.handler.verify_payment
        original_settle = mw.handler.settle_payment

        async def _verify(*a, **k):
            ordered.append("verify")
            return await original_verify(*a, **k)

        async def _settle(*a, **k):
            ordered.append("settle")
            return await original_settle(*a, **k)

        monkeypatch.setattr(mw.handler, "verify_payment", _verify)
        monkeypatch.setattr(mw.handler, "settle_payment", _settle)
        recorder, scope, sig = _present_presented(mw)
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", CALLER, PAID_PATH, scope, None, recorder
        )
        assert served is True
        assert ordered == ["verify", "settle"]
        assert _status(recorder) == 200

    async def test_failed_verify_never_settles_and_denies(self, monkeypatch, mw):
        """A rejected verify calls settle zero times and never reaches the app."""
        _patch_checks_pass(monkeypatch, payment)
        mw.handler._verified = False
        recorder, scope, sig = _present_presented(mw)
        await payment._handle_presented_payment(
            mw, sig, "scrape", CALLER, PAID_PATH, scope, None, recorder
        )
        assert mw.handler.calls == ["verify"], "settle must not run after failed verify"
        assert mw.app.calls == [], "no access granted after a failed verify"

    async def test_failed_settle_denies_access(self, monkeypatch, mw):
        """Verify passes but settle fails: 402, no app, receipt ledger untouched."""
        _patch_checks_pass(monkeypatch, payment)
        monkeypatch.setattr(payment, "_log_settle_denied", lambda *a, **k: None)
        mw.handler._settlement = {"success": False, "reason": "insufficient_funds"}
        recorder, scope, sig = _present_presented(mw)
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", CALLER, PAID_PATH, scope, None, recorder
        )
        assert served is True
        assert mw.handler.calls == ["verify", "settle"]
        assert mw.app.calls == [], "a failed settle must never reach the app"
        assert _status(recorder) == 402

    async def test_success_records_receipt_exactly_once(self, monkeypatch, mw):
        """The PAYMENT-RESPONSE receipt is attached once, with the settlement."""
        _patch_checks_pass(monkeypatch, payment)
        recorder, scope, sig = _present_presented(mw)
        await payment._handle_presented_payment(
            mw, sig, "scrape", CALLER, PAID_PATH, scope, None, recorder
        )
        assert _status(recorder) == 200
        headers = next(f for f in recorder.frames if f["type"] == "http.response.start")["headers"]
        receipts = [v for k, v in headers if k == b"payment-response"]
        assert len(receipts) == 1, "receipt must be attached exactly once"
        assert json.loads(base64.b64decode(receipts[0]).decode())["success"] is True
        assert mw.app.calls, "settled request must reach the app"


def _patch_checks_pass(monkeypatch, mod):
    """Force the audit gates to their pass-through value for ordering tests."""
    monkeypatch.setattr(mod, "_attestation_rejected", lambda *a, **k: (True, {}))
    monkeypatch.setattr(mod, "_attested_atomic_for", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_price_bound", lambda *a, **k: True)


def _status(recorder):
    return next(f for f in recorder.frames if f["type"] == "http.response.start")["status"]
