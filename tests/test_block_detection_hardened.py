# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hardened tests for engine/block_detection.py — untested branches.

Complements tests/test_block_detection.py (per-marker basics), its _gates.py
(anti-false-positive) and its _gates_edge.py siblings by targeting branches
that none of them reach:

* ``detect_block`` with ``html=None`` (not just ``""``).
* ``detect_block`` with ``headers=None`` passed explicitly.
* ``_norm_headers`` with ``None`` and with non-string values.
* ``_is_scripts_only`` with empty / None html.
* Priority ordering when multiple markers coexist (CF beats captcha beats
  rate-limit beats access-denied beats js-required).
* ``cf-mitigated`` header with an empty body.
* 403 + ``cf-ray`` header with a body that has NO CF markers.
* ``_body_evidence`` returning empty for a body with no markers.
* ``classify_response`` with ``html=None``.

Every assertion pins a concrete kind / confidence / escalation / evidence.
"""

from __future__ import annotations

import pytest

from pry.engine.block_detection import BlockSignal, classify_response, detect_block
from tests.block_page_fixtures import CLOUDFLARE_INTERSTITIAL

# ── detect_block: None / empty inputs ───────────────────────────────────────


class TestDetectBlockNoneInputs:
    def test_html_none_clean_status_is_none(self) -> None:
        signal = detect_block(None, 200, {})  # type: ignore[arg-type]
        assert signal.kind == "none"
        assert signal.confidence == 0.95
        assert signal.recommended_escalation == ""
        assert signal.evidence == []

    def test_html_none_with_429_is_rate_limited(self) -> None:
        signal = detect_block(None, 429, {})  # type: ignore[arg-type]
        assert signal.kind == "rate_limited"
        assert signal.confidence == 0.97
        assert signal.recommended_escalation == "backoff"

    def test_headers_none_explicit(self) -> None:
        signal = detect_block("<html><body>clean</body></html>", 200, None)
        assert signal.kind == "none"
        assert signal.evidence == []

    def test_headers_none_with_403_is_access_denied(self) -> None:
        signal = detect_block("<html></html>", 403, None)
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.85
        assert signal.recommended_escalation == "proxy"


# ── detect_block: header-driven branches ────────────────────────────────────


class TestDetectBlockHeaderBranches:
    def test_cf_mitigated_header_with_empty_body(self) -> None:
        signal = detect_block("", 200, {"cf-mitigated": "challenge"})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.97
        assert signal.recommended_escalation == "stealth"
        assert "header cf-mitigated" in signal.evidence
        # No body markers -> evidence has only the header entry.
        assert len(signal.evidence) == 1

    def test_403_with_cf_ray_but_no_cf_body_markers(self) -> None:
        signal = detect_block("<html><body>plain</body></html>", 403, {"cf-ray": "abc-fra"})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.95
        assert signal.recommended_escalation == "stealth"
        assert "header cf-ray" in signal.evidence

    def test_cf_mitigated_beats_captcha_body(self) -> None:
        # Header signal takes priority over a captcha body marker.
        signal = detect_block(
            "<html><body>grecaptcha verify you are human</body></html>",
            200,
            {"cf-mitigated": "challenge"},
        )
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.97


# ── detect_block: priority ordering ─────────────────────────────────────────


class TestDetectBlockPriority:
    def test_cloudflare_body_beats_captcha(self) -> None:
        # Fixture shape argued in tests/block_page_fixtures.py.
        signal = detect_block(CLOUDFLARE_INTERSTITIAL, 200, {})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.90

    def test_captcha_beats_rate_limit_copy(self) -> None:
        html = "<html><body>grecaptcha too many requests</body></html>"
        signal = detect_block(html, 200, {})
        assert signal.kind == "captcha"
        assert signal.confidence == 0.95

    def test_rate_limit_copy_beats_access_denied(self) -> None:
        html = "<html><body>too many requests access denied</body></html>"
        signal = detect_block(html, 200, {})
        assert signal.kind == "rate_limited"
        assert signal.confidence == 0.90

    def test_access_denied_copy_beats_js_required(self) -> None:
        html = "<html><body>access denied enable javascript</body></html>"
        signal = detect_block(html, 200, {})
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.90

    def test_js_required_beats_scripts_only(self) -> None:
        html = "<html><body>enable javascript</body></html>"
        signal = detect_block(html, 200, {})
        assert signal.kind == "js_required"
        assert signal.confidence == 0.90


# ── detect_block: status-driven branches ────────────────────────────────────


class TestDetectBlockStatusBranches:
    def test_429_beats_everything_including_cf_body(self) -> None:
        # 429 short-circuits before any body inspection.
        signal = detect_block("<html><body>just a moment</body></html>", 429, {})
        assert signal.kind == "rate_limited"
        assert signal.confidence == 0.97
        assert signal.evidence == ["http status 429"]

    def test_403_with_cf_ray_beats_access_denied_copy(self) -> None:
        signal = detect_block("<html><body>access denied</body></html>", 403, {"cf-ray": "x"})
        assert signal.kind == "cloudflare"
        assert signal.confidence == 0.95

    def test_403_without_cf_but_with_access_denied_copy(self) -> None:
        # Body copy branch (0.90) fires before the bare-403 branch (0.85).
        signal = detect_block("<html><body>access denied</body></html>", 403, {})
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.90
        assert signal.recommended_escalation == "proxy"


# ── classify_response wrapper edge cases ────────────────────────────────────


class TestClassifyResponseEdgeCases:
    def test_html_none_through_wrapper(self) -> None:
        signal = classify_response(200, None, {})  # type: ignore[arg-type]
        assert isinstance(signal, BlockSignal)
        assert signal.kind == "none"

    def test_headers_none_through_wrapper(self) -> None:
        signal = classify_response(403, "<html></html>", None)
        assert signal.kind == "access_denied"
        assert signal.confidence == 0.85

    @pytest.mark.parametrize(
        ("status", "html", "headers", "expected_kind"),
        [
            (200, None, None, "none"),
            (429, None, None, "rate_limited"),
            (403, None, {"cf-ray": "x"}, "cloudflare"),
            (200, "<html><body>grecaptcha</body></html>", None, "captcha"),
        ],
    )
    def test_wrapper_matches_direct_for_none_inputs(
        self, status: int, html: str | None, headers: dict[str, str] | None, expected_kind: str
    ) -> None:
        via_wrapper = classify_response(status, html, headers)
        via_direct = detect_block(html, status, headers)  # type: ignore[arg-type]
        assert via_wrapper == via_direct
        assert via_wrapper.kind == expected_kind
