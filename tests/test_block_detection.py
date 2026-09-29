# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the adaptive block detection and escalation engine."""

from __future__ import annotations

import pytest

from pry.engine.block_detection import (
    _MAX_BLOCK_COPY_BYTES,
    BlockSignal,
    classify_response,
    detect_block,
)

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


# ── False-positive regression gates ─────────────────────────────────────────
#
# Two gates were added after VALID fetches were thrown away (aa72ad7a, 1b99b4b8):
#
#   * _MIN_BODY_MARKERS_FOR_BLOCK — one incidental marker is not evidence.
#     A 744,148-byte article served by theblock.co contains
#     "challenge-platform" and "grecaptcha" once each and was discarded.
#   * _MAX_BLOCK_COPY_BYTES — generic copy ("forbidden", "access denied",
#     "too many requests", "enable javascript") is only conclusive on a page
#     small enough for the copy to BE the page. A 313,783-byte article
#     mentioning "forbidden" once was discarded.
#
# These are regression gates, not coverage padding: each one must go red if the
# corresponding gate is removed or loosened.

#: Deterministic filler for building realistically-sized bodies. Real article
#: text is long prose, so padding with words (not one repeated character) keeps
#: the synthetic page honest about what a large body actually looks like.
_FILLER = (
    "The court filings describe a dispute over digital assets and the "
    "arbitration panel has yet to publish its ruling. "
)


def _large_body(phrase: str, target_bytes: int) -> str:
    """Return an article-sized body that contains ``phrase`` exactly once.

    The phrase is placed mid-body so it cannot be mistaken for a block page
    that happens to be short. Caller asserts on the resulting size.
    """
    head = "<html><body><article><p>"
    tail = "</p></article></body></html>"
    body = _FILLER * (target_bytes // len(_FILLER) + 1)
    marker_at = len(body) // 2
    return head + body[:marker_at] + phrase + body[marker_at:] + tail


class TestSizeGateDoesNotDropValidFetches:
    """A large page with one incidental marker is a valid fetch, not a block."""

    def test_large_article_with_challenge_platform_and_grecaptcha_is_none(self) -> None:
        # The exact rejected fetch: ~744 KB carrying CF's challenge-platform
        # script (injected into every served page) plus a provider widget ref.
        html = _large_body(
            '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script>'
            "<span>powered by grecaptcha</span>",
            744_148,
        )
        assert len(html) > 600_000
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.recommended_escalation == ""
        assert signal.evidence == []

    def test_large_article_mentioning_forbidden_is_none(self) -> None:
        # The other rejected fetch: ~313 KB article ABOUT a forbidden topic.
        html = _large_body("the ruling declared the token forbidden in that jurisdiction", 313_783)
        assert len(html) > 300_000
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.recommended_escalation == ""
        assert signal.evidence == []

    def test_large_page_with_no_markers_is_none(self) -> None:
        html = _large_body("no anti-bot marker appears anywhere in this body", 200_000)
        assert len(html) > 200_000
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.evidence == []

    @pytest.mark.parametrize(
        ("phrase", "expected_kind"),
        [
            ("the endpoint returned a forbidden response", "none"),
            ("access denied is documented in the terms", "none"),
            ("too many requests is a documented throttle", "none"),
            ("please enable javascript for the full report", "none"),
        ],
    )
    def test_large_page_ignores_each_generic_copy_marker(
        self, phrase: str, expected_kind: str
    ) -> None:
        html = _large_body(phrase, 200_000)
        assert len(html) > _MAX_BLOCK_COPY_BYTES
        assert detect_block(html, 200, {}).kind == expected_kind


class TestWeakMarkerAloneIsNotEvidence:
    """challenge-platform ships in every CF-served page — it proves nothing."""

    def test_challenge_platform_alone_yields_no_evidence(self) -> None:
        html = (
            '<html><body><script src="/cdn-cgi/challenge-platform/h/b/orchestrate/'
            'jsch/v1"></script><p>Ordinary article body.</p></body></html>'
        )
        assert "challenge-platform" in html.lower()
        assert "just a moment" not in html.lower()
        assert "cf-chl-" not in html.lower()
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.evidence == []

    def test_weak_plus_strong_marker_together_is_still_blocked(self) -> None:
        # The gate must not become so permissive that a real interstitial
        # carrying the weak marker slips through.
        html = (
            "<html><head><title>Just a moment...</title></head><body>"
            '<div class="cf-chl-opt">Checking your browser</div>'
            '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1">'
            "</script></body></html>"
        )
        signal = detect_block(html, 200, {})
        assert signal.kind == "cloudflare"
        assert signal.recommended_escalation == "stealth"
        assert len(signal.evidence) >= 2


class TestBlockPagesStillDetected:
    """The size gate must not have gone so far as to miss real blocks."""

    def test_short_cloudflare_interstitial_is_cloudflare(self) -> None:
        html = (
            "<html><head><title>Just a moment...</title></head><body>"
            '<div class="cf-chl-opt">Checking your browser before accessing.</div>'
            '<div class="g-recaptcha" data-sitekey="0x4"></div>'
            '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1">'
            "</script></body></html>"
        )
        assert len(html) < _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 200, {})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.90
        assert signal.recommended_escalation == "stealth"

    def test_small_plain_403_copy_page_is_access_denied(self) -> None:
        html = "<html><body><h1>403 Forbidden</h1><p>nginx</p></body></html>"
        assert len(html) < _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 200, {})
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.80
        assert signal.recommended_escalation == "proxy"


class TestSizeGateBoundary:
    """Pin the 64 KB edge from BOTH sides using the real constant.

    The threshold is read from the module, not hardcoded, so the test tracks a
    deliberate retune instead of silently passing at the wrong boundary.
    """

    @staticmethod
    def _page_of_exactly(size: int) -> str:
        """Build a body of exactly ``size`` bytes ending in 'forbidden'."""
        head = "<html><body><h1>"
        tail = "forbidden</h1></body></html>"
        return head + ("x" * (size - len(head) - len(tail))) + tail

    def test_constant_is_64_kib(self) -> None:
        # Documents the shipped threshold; retuning it is a behaviour change
        # and must be a deliberate edit here, not a silent drift.
        assert _MAX_BLOCK_COPY_BYTES == 64 * 1024

    def test_just_under_boundary_is_still_detected(self) -> None:
        size = _MAX_BLOCK_COPY_BYTES - 1
        html = self._page_of_exactly(size)
        assert len(html) == size
        signal = detect_block(html, 200, {})
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.80

    def test_exactly_at_boundary_is_still_detected(self) -> None:
        # The gate is `<=`, so the boundary byte itself is block copy.
        html = self._page_of_exactly(_MAX_BLOCK_COPY_BYTES)
        assert len(html) == _MAX_BLOCK_COPY_BYTES
        assert detect_block(html, 200, {}).kind == "access_denied"

    def test_just_over_boundary_is_not_block_copy(self) -> None:
        size = _MAX_BLOCK_COPY_BYTES + 1
        html = self._page_of_exactly(size)
        assert len(html) == size
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.evidence == []


class TestHeaderEvidenceIsNotGated:
    """Header signals are authoritative and were never size-gated."""

    def test_cf_mitigated_header_on_large_body_still_cloudflare(self) -> None:
        html = _large_body("the body is large and irrelevant to the header", 300_000)
        assert len(html) > _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 403, {"cf-mitigated": "challenge"})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.97
        assert "header cf-mitigated" in signal.evidence

    def test_cf_ray_plus_403_on_large_body_still_cloudflare(self) -> None:
        html = _large_body("the body is large and irrelevant to the header", 300_000)
        assert len(html) > _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 403, {"cf-ray": "abc123-fra", "server": "cloudflare"})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.95
        assert "header cf-ray" in signal.evidence

    def test_bare_403_on_large_body_still_access_denied(self) -> None:
        # A 403 status is a refusal regardless of how large the error page is.
        html = _large_body("a large upstream error page", 300_000)
        assert len(html) > _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 403, {})
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.85
        assert signal.recommended_escalation == "proxy"
