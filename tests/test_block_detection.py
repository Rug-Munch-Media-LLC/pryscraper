# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the adaptive block detection and escalation engine."""

from __future__ import annotations

import pytest

from block_detection import BlockSignal, classify_response, detect_block

# ── Fixture HTML snippets ──────────────────────────────────────────────────

CF_CHALLENGE_HTML = """<!DOCTYPE html>
<html><head><title>Just a moment...</title></head>
<body><div class="cf-chl-opt">Checking your browser before accessing.</div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script>
</body></html>"""

CF_403_HTML = "<html><body><h1>Access denied</h1></body></html>"

RECAPTCHA_HTML = """<!DOCTYPE html>
<html><head><script src="https://www.google.com/recaptcha/api.js"></script></head>
<body><div class="g-recaptcha" data-sitekey="6Lc..."></div>
<script>grecaptcha.execute();</script>
<p>Please verify you are human.</p></body></html>"""

HCAPTCHA_HTML = (
    '<html><body><script src="https://hcaptcha.com/1/api.js" async defer></script>'
    '<div class="h-captcha" data-sitekey="abc"></div></body></html>'
)

TURNSTILE_HTML = (
    '<html><body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" '
    'async defer></script><div class="cf-turnstile" data-sitekey="0x4"></div></body></html>'
)

HUMAN_CHECK_HTML = (
    "<html><body><p>Please complete the security check. "
    "Verify you are human to continue.</p></body></html>"
)

RATE_LIMIT_HTML = (
    "<html><body><h1>Too many requests</h1><p>Please try again later.</p></body></html>"
)

ACCESS_DENIED_HTML = (
    "<html><body><h1>Access Denied</h1><p>You don't have permission.</p></body></html>"
)

FORBIDDEN_HTML = "<html><body><h1>403 Forbidden</h1><p>nginx</p></body></html>"

JS_REQUIRED_HTML = (
    "<html><head><title>Site</title></head><body>"
    "<noscript>Please enable JavaScript to view this page.</noscript>"
    '<div id="app"></div></body></html>'
)

SCRIPTS_ONLY_HTML = (
    "<html><head></head><body>"
    '<script src="/assets/app.js"></script>'
    "<script>window.__DATA__ = {};</script>"
    "</body></html>"
)

CLEAN_HTML = """<!DOCTYPE html>
<html><head><title>Example</title></head>
<body><h1>Welcome</h1>
<p>This is a perfectly normal page with lots of useful text content.</p>
<a href="/about">About</a></body></html>"""


# ── Cloudflare ─────────────────────────────────────────────────────────────


def test_cloudflare_challenge_body_markers() -> None:
    signal = detect_block(CF_CHALLENGE_HTML, 403, {"server": "cloudflare"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "stealth"
    assert any("just a moment" in e for e in signal.evidence)
    assert any("cf-chl-" in e for e in signal.evidence)


def test_cloudflare_cf_mitigated_header() -> None:
    signal = detect_block("<html><body>blocked</body></html>", 403, {"cf-mitigated": "challenge"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.97
    assert signal.recommended_escalation == "stealth"
    assert "header cf-mitigated" in signal.evidence


def test_cloudflare_403_with_cf_ray_header() -> None:
    signal = detect_block(CF_403_HTML, 403, {"cf-ray": "abc123-fra", "server": "cloudflare"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.95
    assert signal.recommended_escalation == "stealth"
    assert any("cf-ray" in e for e in signal.evidence)


def test_cloudflare_header_keys_case_insensitive() -> None:
    signal = detect_block("<html></html>", 403, {"CF-Ray": "abc123-fra"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.95


def test_403_without_cf_is_access_denied_not_cloudflare() -> None:
    signal = detect_block(CF_403_HTML, 403, {"server": "nginx"})
    assert signal.kind == "access_denied"
    assert signal.recommended_escalation == "proxy"


# ── CAPTCHA ────────────────────────────────────────────────────────────────


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


# ── Rate limited ───────────────────────────────────────────────────────────


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


# ── Access denied ──────────────────────────────────────────────────────────


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


# ── JS required ────────────────────────────────────────────────────────────


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


# ── Clean / no block ───────────────────────────────────────────────────────


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


# ── classify_response wrapper ──────────────────────────────────────────────


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
