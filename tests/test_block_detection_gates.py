# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""False-positive regression gates for the adaptive block detection engine.

Two gates were added after VALID fetches were thrown away (aa72ad7a, 1b99b4b8):

  * _MIN_BODY_MARKERS_FOR_BLOCK — one incidental marker is not evidence.
    A 744,148-byte article served by theblock.co contains
    "challenge-platform" and "grecaptcha" once each and was discarded.
  * _MAX_BLOCK_COPY_BYTES — generic copy ("forbidden", "access denied",
    "too many requests", "enable javascript") is only conclusive on a page
    small enough for the copy to BE the page. A 313,783-byte article
    mentioning "forbidden" once was discarded.

These are regression gates, not coverage padding: each one must go red if the
corresponding gate is removed or loosened. Split out of
tests/test_block_detection.py, which keeps the per-marker basics.
"""

from __future__ import annotations

import pytest

from pry.engine.block_detection import _MAX_BLOCK_COPY_BYTES, detect_block
from tests.block_gate_helpers import _large_body


class TestSingleMarkerCaptchaIsStillDetected:
    """The CAPTCHA path must detect a page carrying exactly ONE widget marker.

    Regression gate for the 2+ density gate (aa72ad7a), which was built on
    Cloudflare's shape — a real CF interstitial carries "just a moment",
    "cf-chl-" and "challenge-platform" together — and then applied to a
    differently-shaped threat. A real hCaptcha or Turnstile interstitial
    typically carries ONE marker, so the density rule made single-CAPTCHA
    pages undetectable: a 108-byte hCaptcha page classified as js_required,
    a Turnstile page as a bare access_denied 403.

    The marker in each case below is the ONLY one present. If a density gate
    is ever reapplied to the CAPTCHA path, these go red.

    The escape from false positives is the 64 KB size gate, not marker count:
    a real widget page IS the response, whereas a 744 KB article naming a
    widget in its own JS bundle is a valid fetch. That pairing is pinned by
    TestSizeGateDoesNotDropValidFetches and by
    test_large_page_with_single_captcha_marker_is_none below.
    """

    #: (name, body, status, expected_confidence) — one marker each, no others.
    SINGLE_MARKER_CASES = (
        (
            "hcaptcha",
            '<html><body><script src="https://hcaptcha.com/1/api.js" async defer></script>'
            '<div class="h-captcha" data-sitekey="abc"></div></body></html>',
            200,
            0.95,
        ),
        (
            "turnstile",
            '<html><body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" '
            'async defer></script><div class="cf-turnstile" data-sitekey="0x4"></div></body></html>',
            403,
            0.95,
        ),
        (
            "grecaptcha",
            '<html><body><div class="g-recaptcha" data-sitekey="6Lc"></div>'
            "<script>grecaptcha.execute();</script></body></html>",
            200,
            0.95,
        ),
        (
            "generic copy only",
            "<html><body><p>Verify you are human to continue.</p></body></html>",
            200,
            0.90,
        ),
    )

    @pytest.mark.parametrize(
        ("name", "body", "status", "expected_confidence"),
        SINGLE_MARKER_CASES,
        ids=[case[0] for case in SINGLE_MARKER_CASES],
    )
    def test_single_marker_page_is_captcha(
        self, name: str, body: str, status: int, expected_confidence: float
    ) -> None:
        lower = body.lower()
        # The premise of the test: exactly ONE captcha marker is present. If
        # this ever fails the test is no longer pinning the single-marker rule.
        present = [
            m
            for m in ("grecaptcha", "hcaptcha.com", "turnstile", "verify you are human")
            if m in lower
        ]
        assert len(present) == 1, f"fixture must carry exactly one marker, found {present}"
        assert len(body) < _MAX_BLOCK_COPY_BYTES

        signal = detect_block(body, status, {})
        assert signal.kind == "captcha", f"{name}: single-marker page must be a captcha block"
        assert signal.confidence == expected_confidence
        assert signal.recommended_escalation == "stealth"
        assert signal.evidence, "a block must always carry its evidence"

    def test_large_page_with_single_captcha_marker_is_none(self) -> None:
        """The other half of the contract: one marker on a LARGE page is not a block.

        This is the theblock.co fetch (744,148 bytes naming a widget once).
        Without the size gate, restoring the single-marker rule would throw
        that valid article away again — so both halves must hold together.
        """
        html = _large_body(
            '<script src="https://hcaptcha.com/1/api.js"></script><span>powered by grecaptcha</span>',
            744_148,
        )
        assert len(html) > _MAX_BLOCK_COPY_BYTES
        signal = detect_block(html, 200, {})
        assert signal.kind == "none"
        assert signal.evidence == []


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
