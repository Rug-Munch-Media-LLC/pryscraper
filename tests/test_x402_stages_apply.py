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

import base64
import json
from typing import Any

from pry.payments.x402_middleware import (
    enforcement_payment as payment,
)
from tests._x402_stage_fakes import _decoded, _FakeHandler, _FakeMW, _Recorder, _sig


class TestVerifyAndSettleOrdering:
    """The payment-critical invariant: verify BEFORE settle."""

    async def test_verify_then_settle_in_order(self):
        handler = _FakeHandler(settlement={"success": True})
        mw = _FakeMW(handler=handler)
        parsed = ("p1", "0xabc", "base", "USDC", 0.01)
        settlement = await payment._verify_and_settle(mw, parsed, "scrape", "caller", None)
        assert handler.calls == ["verify", "settle"]
        assert settlement == {"success": True}

    async def test_failed_verify_stops_before_settle(self):
        handler = _FakeHandler(verified=False)
        mw = _FakeMW(handler=handler)
        parsed = ("p1", "0xabc", "base", "USDC", 0.01)
        settlement = await payment._verify_and_settle(mw, parsed, "scrape", "caller", None)
        assert settlement is None
        assert handler.calls == ["verify"], "settle must not run after a failed verify"

    async def test_attested_atomic_is_passed_to_verify(self):
        handler = _FakeHandler()
        mw = _FakeMW(handler=handler)
        parsed = ("p1", "0xabc", "base", "USDC", 0.01)
        await payment._verify_and_settle(mw, parsed, "scrape", "caller", 12_345)
        assert handler.verify_kwargs["attested_required_atomic"] == 12_345
        assert handler.verify_kwargs["operation"] == "scrape"


class TestServeSettled:
    """Serving attaches the PAYMENT-RESPONSE receipt header + verification."""

    async def test_serve_attaches_receipt_and_stamps_scope(self):
        mw = _FakeMW()
        recorder = _Recorder()
        scope: dict[str, Any] = {}
        settlement = {"success": True, "tx": "0xabc"}
        await payment._serve_settled(
            mw, scope, None, recorder, settlement, "p1", "0xabc", "caller", "scrape"
        )
        result = _decoded(recorder.frames)
        assert result["status"] == 200
        receipt = json.loads(base64.b64decode(result["headers"][b"payment-response"]).decode())
        assert receipt == settlement
        assert scope["x402_verified"]["payment_id"] == "p1"
        assert scope["x402_verified"]["tx_hash"] == "0xabc"


class TestHandlePresentedPayment:
    """The full presented-signature path: decode → attest → settle → serve."""

    def _mw(self, *, handler=None, verifier=None) -> _FakeMW:
        return _FakeMW(handler=handler or _FakeHandler(), verifier=verifier, network="base")

    async def test_undecodable_signature_declines(self):
        mw = self._mw()
        recorder = _Recorder()
        served = await payment._handle_presented_payment(
            mw, "!!!bad!!!", "scrape", "caller", "/v1/scrape", {}, None, recorder
        )
        assert served is False

    async def test_happy_path_serves_with_attested_zero(self, monkeypatch):
        handler = _FakeHandler(settlement={"success": True})
        mw = self._mw(handler=handler)
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (True, {}))
        monkeypatch.setattr(payment, "_attested_atomic_for", lambda *a, **k: None)
        monkeypatch.setattr(payment, "_price_bound", lambda *a, **k: True)

        sig = _sig({"payment_id": "p1", "tx_hash": "0xabc", "amount_usd": 0.01})
        recorder = _Recorder()
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", "caller", "/v1/scrape", {}, None, recorder
        )
        assert served is True
        assert handler.calls == ["verify", "settle"]
        assert _decoded(recorder.frames)["status"] == 200

    async def test_rejected_attestation_sends_402_and_stops(self, monkeypatch):
        handler = _FakeHandler()
        sent: list[Any] = []

        async def _verify(operation, path, send):
            sent.append((operation, path))

        mw = self._mw(handler=handler, verifier=_verify)
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (False, {}))
        sig = _sig({"payment_id": "p1", "tx_hash": "0xabc", "amount_usd": 0.01})
        recorder = _Recorder()
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", "caller", "/v1/scrape", {}, None, recorder
        )
        assert served is True
        assert sent == [("scrape", "/v1/scrape")]
        assert handler.calls == [], "no verify/settle after a rejected attestation"

    async def test_price_unbound_sends_402_and_stops(self, monkeypatch):
        handler = _FakeHandler()
        sent: list[Any] = []

        async def _verify(operation, path, send):
            sent.append((operation, path))

        mw = self._mw(handler=handler, verifier=_verify)
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (True, {}))
        monkeypatch.setattr(payment, "_attested_atomic_for", lambda *a, **k: None)
        monkeypatch.setattr(payment, "_price_bound", lambda *a, **k: False)
        sig = _sig({"payment_id": "p1", "tx_hash": "0xabc", "amount_usd": 0.01})
        recorder = _Recorder()
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", "caller", "/v1/scrape", {}, None, recorder
        )
        assert served is True
        assert sent == [("scrape", "/v1/scrape")]
        assert handler.calls == [], "no verify/settle after an unbound price"

    async def test_settle_failure_sends_402_and_stops(self, monkeypatch):
        handler = _FakeHandler(settlement={"success": False, "reason": "nope"})
        sent: list[Any] = []

        async def _verify(operation, path, send):
            sent.append((operation, path))

        mw = self._mw(handler=handler, verifier=_verify)
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (True, {}))
        monkeypatch.setattr(payment, "_attested_atomic_for", lambda *a, **k: None)
        monkeypatch.setattr(payment, "_price_bound", lambda *a, **k: True)
        monkeypatch.setattr(payment, "_log_settle_denied", lambda *a, **k: None)
        sig = _sig({"payment_id": "p1", "tx_hash": "0xabc", "amount_usd": 0.01})
        recorder = _Recorder()
        served = await payment._handle_presented_payment(
            mw, sig, "scrape", "caller", "/v1/scrape", {}, None, recorder
        )
        assert served is True
        assert sent == [("scrape", "/v1/scrape")]
        assert handler.calls == ["verify", "settle"]
        assert mw.app.calls == [], "a failed settle must never reach the app"
