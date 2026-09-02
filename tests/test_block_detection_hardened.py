# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hardened tests for engine/block_detection.py — untested branches.

Complements tests/test_block_detection.py by targeting branches that suite
does not reach:

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

from pry.engine.block_detection import (
    BlockSignal,
    _body_evidence,
    _is_scripts_only,
    _norm_headers,
    classify_response,
    detect_block,
)

# ── _norm_headers ───────────────────────────────────────────────────────────


class TestNormHeaders:
    def test_none_returns_empty_dict(self) -> None:
        assert _norm_headers(None) == {}

    def test_empty_dict_returns_empty_dict(self) -> None:
        assert _norm_headers({}) == {}

    def test_keys_lowercased_and_values_stringified(self) -> None:
        result = _norm_headers({"CF-Ray": "abc", "Server": 123})
        assert result == {"cf-ray": "abc", "server": "123"}

    def test_mixed_case_keys_collapse(self) -> None:
        result = _norm_headers({"CF-Ray": "a", "cf-ray": "b"})
        assert result == {"cf-ray": "b"}  # later key wins


# ── _body_evidence ──────────────────────────────────────────────────────────


class TestBodyEvidence:
    def test_no_markers_returns_empty_list(self) -> None:
        assert _body_evidence(("just a moment",), "clean body text") == []

    def test_markers_found_return_evidence_strings(self) -> None:
        result = _body_evidence(("just a moment", "cf-chl-"), "just a moment please")
        assert result == ["body contains 'just a moment'"]

    def test_only_present_markers_are_reported(self) -> None:
        result = _body_evidence(("a", "b", "c"), "has a and c")
        assert result == ["body contains 'a'", "body contains 'c'"]


# ── _is_scripts_only ────────────────────────────────────────────────────────


class TestIsScriptsOnly:
    def test_empty_html_is_false(self) -> None:
        assert _is_scripts_only("") is False

    def test_none_html_is_false(self) -> None:
        assert _is_scripts_only(None) is False  # type: ignore[arg-type]

    def test_visible_text_means_not_scripts_only(self) -> None:
        html = "<script>var x=1;</script><p>real content here</p>"
        assert _is_scripts_only(html) is False

    def test_scripts_with_no_visible_text_is_true(self) -> None:
        html = "<html><body><script>window.__DATA__={};</script></body></html>"
        assert _is_scripts_only(html) is True

    def test_script_content_does_not_count_as_visible(self) -> None:
        # The JS inside <script> must be stripped before the visible-text check.
        html = "<script>lots of javascript words here that are not visible</script>"
        assert _is_scripts_only(html) is True


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
        html = "<html><body>just a moment grecaptcha</body></html>"
        signal = detect_block(html, 200, {})
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
