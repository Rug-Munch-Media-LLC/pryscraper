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

import pytest

from pry.payments.x402_middleware import (
    enforcement_payment as payment,
    enforcement_payment_checks as checks,
    enforcement_stages as stages,
)


def _sig(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _decoded(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Reassemble an ASGI send stream into a status + headers + body dict."""
    start = next(f for f in frames if f["type"] == "http.response.start")
    body = b"".join(f.get("body", b"") for f in frames if f["type"] == "http.response.body")
    parsed_body: Any = None
    if body:
        try:
            parsed_body = json.loads(body)
        except ValueError:
            parsed_body = body
    return {
        "status": start["status"],
        "headers": dict(start.get("headers", [])),
        "body": parsed_body,
    }


class _Recorder:
    """Collects ASGI messages from a fake ``send`` callable."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.frames.append(message)


class _FakeApp:
    """Records that the wrapped app was served, with the scope it saw."""

    def __init__(self, status: int = 200) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _FakeHandler:
    """Fake X402Handler exposing the verify/settle contract the gate drives."""

    def __init__(
        self,
        *,
        verified: bool = True,
        settlement: dict[str, Any] | None = None,
        paid: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.verify_kwargs: dict[str, Any] = {}
        self.settle_kwargs: dict[str, Any] = {}
        self._verified = verified
        self._settlement = settlement if settlement is not None else {"success": True}
        self._paid = paid

    def refresh(self) -> None:
        self.calls.append("refresh")

    async def verify_payment(self, payment_id, tx_hash, **kwargs):
        self.calls.append("verify")
        self.verify_kwargs = {"payment_id": payment_id, "tx_hash": tx_hash, **kwargs}
        return {"verified": self._verified}

    async def settle_payment(self, payment_id, tx_hash, **kwargs):
        self.calls.append("settle")
        self.settle_kwargs = {"payment_id": payment_id, "tx_hash": tx_hash, **kwargs}
        return self._settlement

    def is_paid(self, payment_id, **kwargs):
        return self._paid


class _FakeMW:
    """Minimal middleware stand-in with only the attributes stages touch."""

    def __init__(self, *, handler=None, verifier=None, network="base") -> None:
        self.app = _FakeApp()
        self.handler = handler or _FakeHandler()
        self.network = network
        self._free = False
        self._verifier = verifier

    def _is_free(self, path):
        return self._free

    async def _send_payment_required(self, operation, path, send):
        assert self._verifier is not None
        await self._verifier(operation, path, send)


class TestParsePaymentSignature:
    """Decode is tolerant on garbage and defaults missing fields."""

    def test_parses_known_payload(self):
        parsed = checks._parse_payment_signature(
            _sig(
                {
                    "payment_id": "p1",
                    "tx_hash": "0xabc",
                    "network": "base",
                    "asset": "USDC",
                    "amount_usd": 0.01,
                }
            ),
            "base",
        )
        assert parsed == ("p1", "0xabc", "base", "USDC", 0.01)

    def test_defaults_network_when_absent(self):
        parsed = checks._parse_payment_signature(_sig({"payment_id": "p"}), "base")
        assert parsed is not None
        assert parsed[2] == "base"

    def test_falls_back_to_payload_field_for_tx_hash(self):
        parsed = checks._parse_payment_signature(
            _sig({"payment_id": "p", "payload": "0xdead"}), "base"
        )
        assert parsed is not None
        assert parsed[1] == "0xdead"

    def test_garbage_returns_none(self):
        assert checks._parse_payment_signature("!!!not-base64!!!", "base") is None


class TestSettlePredicates:
    """Missing or non-success settlement must be treated as failure."""

    @pytest.mark.parametrize(
        ("settlement", "expected"),
        [
            (None, True),
            ({}, True),
            ({"success": False}, True),
            ({"success": True}, False),
        ],
        ids=["none", "empty", "not-success", "success"],
    )
    def test_settle_failed_matrix(self, settlement, expected):
        assert checks._settle_failed(settlement) is expected


class TestMisconfiguredGate:
    """A priced-but-unconfigured operation bypasses pricing → fail closed."""

    def test_unconfigured_operation_is_misconfigured(self):
        assert stages._is_misconfigured("__definitely_not_priced__") is True

    def test_configured_operation_is_not_misconfigured(self):
        from pry.payments.x402 import X402_PRICING

        operation = next(iter(X402_PRICING))
        assert stages._is_misconfigured(operation) is False

    async def test_send_misconfigured_returns_500(self):
        recorder = _Recorder()
        await stages._send_misconfigured(recorder, "scrape", "/v1/scrape")
        result = _decoded(recorder.frames)
        assert result["status"] == 500
        assert result["body"]["error"] == "payment_gate_misconfigured"


class TestRateLimitStage:
    """Per-IP limiter: pass-through when allowed, 429 + Retry-After when not."""

    async def test_allowed_returns_true_without_sending(self):
        class _Limiter:
            def check(self, _key):
                return True, {}

        mw = _FakeMW()
        mw.limiter = _Limiter()
        recorder = _Recorder()
        assert await stages._check_rate_limit(mw, "1.2.3.4", "/v1/scrape", recorder) is True
        assert recorder.frames == []

    async def test_denied_returns_false_and_sends_429(self):
        class _Limiter:
            def check(self, _key):
                return False, {"retry_after": 7.9}

        mw = _FakeMW()
        mw.limiter = _Limiter()
        recorder = _Recorder()
        assert await stages._check_rate_limit(mw, "1.2.3.4", "/v1/scrape", recorder) is False
        result = _decoded(recorder.frames)
        assert result["status"] == 429
        assert result["body"]["error"] == "rate_limit_exceeded"
        assert result["headers"][b"retry-after"] == b"7"


class TestBypassGate:
    """Non-HTTP / preflight / owner / internal / free bypass the gate."""

    async def test_non_http_scope_is_served(self):
        mw = _FakeMW()
        recorder = _Recorder()
        scope = {"type": "lifespan"}
        assert await stages._bypass_gate(mw, scope, None, recorder) is True
        assert mw.app.calls == [{"type": "lifespan"}]

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
