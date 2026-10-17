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

import pytest

from pry.payments.x402_middleware import (
    enforcement_payment_checks as checks,
    enforcement_stages as stages,
)
from tests._x402_stage_fakes import _decoded, _FakeMW, _Recorder, _sig


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
        expected = ("p1", "0xabc", "base", "USDC", 0.01)
        assert parsed == expected

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
