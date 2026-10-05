# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Rate-limit and access-denied signal detection."""

from __future__ import annotations

from pry.engine.block_detection import detect_block

from .conftest import ACCESS_DENIED_HTML, FORBIDDEN_HTML, RATE_LIMIT_HTML


def test_http_429_is_rate_limited() -> None:
    signal = detect_block("<html><body>busy</body></html>", 429, {})
    assert signal.kind == "rate_limited"
    assert signal.confidence == 0.97
    assert signal.recommended_escalation == "backoff"
    assert "http status 429" in signal.evidence


def test_soft_block_200_rate_limit_copy() -> None:
    signal = detect_block(RATE_LIMIT_HTML, 200, {})
    assert signal.kind == "rate_limited"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "backoff"
    assert any("too many requests" in e for e in signal.evidence)


def test_access_denied_body_copy() -> None:
    signal = detect_block(ACCESS_DENIED_HTML, 200, {})
    assert signal.kind == "access_denied"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "proxy"


def test_generic_403_without_cf() -> None:
    signal = detect_block("<html><body></body></html>", 403, {})
    assert signal.kind == "access_denied"
    assert signal.confidence == 0.85
    assert signal.recommended_escalation == "proxy"


def test_forbidden_body_copy() -> None:
    # Soft-block: WAF renders "forbidden" copy with a 200 status, so the
    # body marker branch (not the 403 status branch) must fire.
    signal = detect_block(FORBIDDEN_HTML, 200, {})
    assert signal.kind == "access_denied"
    assert signal.confidence == 0.80
    assert signal.recommended_escalation == "proxy"
    assert any("forbidden" in e for e in signal.evidence)
