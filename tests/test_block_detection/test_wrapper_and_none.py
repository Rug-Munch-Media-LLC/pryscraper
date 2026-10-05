# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""JS-required, clean, and classify_response wrapper signal detection."""

from __future__ import annotations

import pytest

from pry.engine.block_detection import BlockSignal, classify_response, detect_block

from .conftest import (
    CF_CHALLENGE_HTML,
    CLEAN_HTML,
    JS_REQUIRED_HTML,
    RECAPTCHA_HTML,
    SCRIPTS_ONLY_HTML,
)


def test_enable_javascript_marker() -> None:
    signal = detect_block(JS_REQUIRED_HTML, 200, {})
    assert signal.kind == "js_required"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "browser"
    assert any("enable javascript" in e for e in signal.evidence)


def test_empty_body_scripts_only() -> None:
    signal = detect_block(SCRIPTS_ONLY_HTML, 200, {})
    assert signal.kind == "js_required"
    assert signal.confidence == 0.75
    assert signal.recommended_escalation == "browser"
    assert any("scripts only" in e for e in signal.evidence)


def test_clean_page_is_none() -> None:
    signal = detect_block(CLEAN_HTML, 200, {})
    assert signal.kind == "none"
    assert signal.confidence == 0.95
    assert signal.recommended_escalation == ""
    assert signal.evidence == []


def test_empty_html_is_none() -> None:
    signal = detect_block("", 200, {})
    assert signal.kind == "none"
    assert signal.confidence == 0.95


def test_none_headers_arg_default() -> None:
    signal = detect_block(CLEAN_HTML, 200)
    assert signal.kind == "none"
    assert signal.evidence == []


@pytest.mark.parametrize(
    ("status", "html", "headers"),
    [
        (403, CF_CHALLENGE_HTML, None),
        (200, RECAPTCHA_HTML, None),
        (429, "<html></html>", None),
        (403, "<html></html>", {"cf-ray": "x-fra"}),
        (200, CLEAN_HTML, None),
    ],
)
def test_classify_response_matches_detect_block(
    status: int, html: str, headers: dict[str, str] | None
) -> None:
    via_wrapper = classify_response(status, html, headers)
    via_direct = detect_block(html, status, headers)
    assert isinstance(via_wrapper, BlockSignal)
    assert via_wrapper == via_direct


def test_classify_response_status_first_convenience() -> None:
    signal = classify_response(429, "<html></html>")
    assert signal.kind == "rate_limited"
    assert signal.recommended_escalation == "backoff"
