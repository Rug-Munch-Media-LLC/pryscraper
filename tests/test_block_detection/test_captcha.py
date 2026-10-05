# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""CAPTCHA signal detection."""

from __future__ import annotations

from pry.engine.block_detection import detect_block

from .conftest import HCAPTCHA_HTML, HUMAN_CHECK_HTML, RECAPTCHA_HTML, TURNSTILE_HTML


def test_recaptcha_marker() -> None:
    signal = detect_block(RECAPTCHA_HTML, 200, {})
    assert signal.kind == "captcha"
    assert signal.confidence == 0.95
    assert signal.recommended_escalation == "stealth"
    assert any("grecaptcha" in e for e in signal.evidence)


def test_hcaptcha_marker() -> None:
    signal = detect_block(HCAPTCHA_HTML, 200, {})
    assert signal.kind == "captcha"
    assert signal.confidence == 0.95


def test_turnstile_marker() -> None:
    signal = detect_block(TURNSTILE_HTML, 403, {})
    assert signal.kind == "captcha"
    assert signal.confidence == 0.95
    assert any("turnstile" in e for e in signal.evidence)


def test_verify_you_are_human_generic_copy() -> None:
    signal = detect_block(HUMAN_CHECK_HTML, 200, {})
    assert signal.kind == "captcha"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "stealth"
