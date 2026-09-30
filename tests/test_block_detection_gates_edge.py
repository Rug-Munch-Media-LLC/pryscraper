# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""False-positive regression gates, part 2 of 2 — the edge cases.

Part 1 is tests/test_block_detection_gates.py (the density and size gates).
This half holds the boundary cases: the weak marker on its own, real block
pages that must still be detected, the 64 KB edge pinned from both sides, and
the header signals that were never size-gated. The rationale for the gates
themselves is in part 1's module docstring.
"""

from __future__ import annotations

from pry.engine.block_detection import _MAX_BLOCK_COPY_BYTES, detect_block
from tests.block_gate_helpers import _large_body


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
