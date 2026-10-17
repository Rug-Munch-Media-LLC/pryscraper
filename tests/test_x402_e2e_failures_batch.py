# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end x402 replay guard, failure matrix and batch partial failure.

Companion to ``test_x402_e2e_ordering.py``. Same in-process flow with a faked
facilitator; here the assertions are about NOT granting access:

- the same payment payload twice must not double-settle (tx replay guard);
- each failure mode (bad sig, rejected attestation, unbound price, misconfig)
  returns the right status and NEVER reaches the app handler;
- a pre-verified batch grants access only to its own caller/operation.
"""

from __future__ import annotations

import pytest

from pry.payments.x402_middleware import (
    enforcement_payment as payment,
    enforcement_stages as stages,
)
from tests._x402_stage_fakes import (
    _fake_middleware,
    _FakeApp,
    _FakeHandler,
    _Recorder,
    _scope as _x402_scope,
    _sig,
)

PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.7"
PID = {"payment_id": "p1", "tx_hash": "0xabc"}


async def _call(mw, sig, *, operation="scrape", path=PAID_PATH):
    """Present one PAYMENT-SIGNATURE to the middleware stage; return (recorder, served)."""
    recorder = _Recorder()
    scope = _x402_scope(payment_sig=sig, caller=CALLER)
    served = await payment._handle_presented_payment(
        mw, sig, operation, CALLER, path, scope, None, recorder
    )
    return recorder, served


def _status(recorder):
    return next(f for f in recorder.frames if f["type"] == "http.response.start")["status"]


def _pass_checks(monkeypatch):
    """Force attestation + price gates to pass (they have their own tests)."""
    monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (True, {}))
    monkeypatch.setattr(payment, "_attested_atomic_for", lambda *a, **k: None)
    monkeypatch.setattr(payment, "_price_bound", lambda *a, **k: True)


@pytest.fixture
def mw(monkeypatch):
    return _fake_middleware(monkeypatch, app=_FakeApp(), handler=_FakeHandler(), network="base")


class TestReplayGuard:
    async def test_replayed_payload_does_not_double_settle(self, monkeypatch, mw):
        """First present settles; a replay (verify now fails) never settles again."""
        _pass_checks(monkeypatch)
        sig = _sig(PID)

        recorder, served = await _call(mw, sig)
        assert served is True
        expected = ["verify", "settle"]
        assert mw.handler.calls == expected
        assert _status(recorder) == 200

        # Replay: real handler rejects the already-consumed tx at verify.
        mw.handler._verified = False
        mw.handler.calls.clear()
        _, served = await _call(mw, sig)
        assert served is False, "failed verify falls back to a fresh 402"
        expected_2 = ["verify"]
        assert mw.handler.calls == expected_2, "a replayed tx must not settle twice"
        assert len(mw.app.calls) == 1, "only the first request reached the app"


class TestFailureMatrix:
    async def test_invalid_signature_declines_and_sends_402(self, monkeypatch, mw):
        """Undecodable PAYMENT-SIGNATURE never reaches verify/settle/app."""
        served = await payment._handle_presented_payment(
            mw, "!!!not-base64!!!", "scrape", CALLER, PAID_PATH, {}, None, _Recorder()
        )
        assert served is False
        assert mw.handler.calls == []
        assert mw.app.calls == []

    async def test_rejected_attestation_is_402_and_no_handler(self, monkeypatch, mw):
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (False, {}))
        recorder, served = await _call(mw, _sig(PID))
        assert served is True
        assert _status(recorder) == 402
        expected = [("scrape", PAID_PATH)]
        assert mw.sent == expected
        assert mw.handler.calls == []
        assert mw.app.calls == []

    async def test_unbound_price_is_402_and_no_handler(self, monkeypatch, mw):
        monkeypatch.setattr(payment, "_attestation_rejected", lambda *a, **k: (True, {}))
        monkeypatch.setattr(payment, "_attested_atomic_for", lambda *a, **k: None)
        monkeypatch.setattr(payment, "_price_bound", lambda *a, **k: False)
        recorder, served = await _call(mw, _sig(PID))
        assert served is True
        assert _status(recorder) == 402
        assert mw.handler.calls == []
        assert mw.app.calls == []

    async def test_misconfigured_gate_is_500_and_no_handler(self, monkeypatch, mw):
        """A priced-but-unconfigured operation fails closed with 500."""
        assert stages._is_misconfigured("__not_priced__") is True
        recorder = _Recorder()
        await stages._send_misconfigured(recorder, "scrape", PAID_PATH)
        result = next(f for f in recorder.frames if f["type"] == "http.response.start")
        assert result["status"] == 500
        assert mw.app.calls == []


class TestPreverifiedBatch:
    """Pre-verified batch access: partial failure semantics."""

    def _seed_batch(self, batch_id, operations, *, caller=CALLER, paid=True):
        from datetime import UTC, datetime, timedelta

        from pry.payments.x402.batch import store

        store._save_batch(
            {
                "batch_id": batch_id,
                "operations": operations,
                "total_usd": 0.02,
                "paid": paid,
                "caller_key": caller,
                "expires_at": (datetime.now(UTC) + timedelta(seconds=600)).isoformat(),
            }
        )

    @pytest.fixture(autouse=True)
    def _clear(self):
        from pry.payments.x402.batch import state

        with state._batch_lock:
            state._batch_payments.clear()
            state._consumed_txs.clear()
        yield
        with state._batch_lock:
            state._batch_payments.clear()
            state._consumed_txs.clear()

    async def test_covered_operation_served(self, mw):
        self._seed_batch("b1", ["scrape", "monitor"])
        served = await stages._serve_preverified_batch(
            mw, {}, None, _Recorder(), "b1", CALLER, "scrape"
        )
        assert served is True
        assert mw.app.calls

    async def test_uncovered_operation_declined(self, mw):
        self._seed_batch("b1", ["scrape"])
        served = await stages._serve_preverified_batch(
            mw, {}, None, _Recorder(), "b1", CALLER, "crawl"
        )
        assert served is False
        assert mw.app.calls == []

    async def test_wrong_caller_declined(self, mw):
        self._seed_batch("b1", ["scrape"], caller="1.1.1.1")
        served = await stages._serve_preverified_batch(
            mw, {}, None, _Recorder(), "b1", CALLER, "scrape"
        )
        assert served is False
        assert mw.app.calls == []

    async def test_unpaid_batch_declined(self, mw):
        self._seed_batch("b1", ["scrape"], paid=False)
        served = await stages._serve_preverified_batch(
            mw, {}, None, _Recorder(), "b1", CALLER, "scrape"
        )
        assert served is False
        assert mw.app.calls == []
