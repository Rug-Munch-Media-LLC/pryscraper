# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Unit tests for the pure helpers in engine/block_markers.py.

Split from tests/test_block_detection_hardened.py on 2026-09-30. These three
functions are pure string functions with no signal, confidence or escalation
logic of their own, and they were moved into block_markers.py alongside the
marker tables they read — so their tests move with them and the file that
tests the CLASSIFIER keeps testing the classifier.

Pure test move: no assertion, fixture or case was changed or dropped.
"""

from __future__ import annotations

from pry.engine.block_detection import _body_evidence, _is_scripts_only, _norm_headers

# ── _norm_headers ───────────────────────────────────────────────────────────


class TestNormHeaders:
    def test_none_returns_empty_dict(self) -> None:
        assert _norm_headers(None) == {}

    def test_empty_dict_returns_empty_dict(self) -> None:
        assert _norm_headers({}) == {}

    def test_keys_lowercased_and_values_stringified(self) -> None:
        result = _norm_headers({"CF-Ray": "abc", "Server": 123})
        expected = {"cf-ray": "abc", "server": "123"}
        assert result == expected

    def test_mixed_case_keys_collapse(self) -> None:
        result = _norm_headers({"CF-Ray": "a", "cf-ray": "b"})
        expected = {"cf-ray": "b"}
        assert result == expected  # later key wins


# ── _body_evidence ──────────────────────────────────────────────────────────


class TestBodyEvidence:
    def test_no_markers_returns_empty_list(self) -> None:
        assert _body_evidence(("just a moment",), "clean body text") == []

    def test_markers_found_return_evidence_strings(self) -> None:
        result = _body_evidence(("just a moment", "cf-chl-"), "just a moment please")
        expected = ["body contains 'just a moment'"]
        assert result == expected

    def test_only_present_markers_are_reported(self) -> None:
        result = _body_evidence(("a", "b", "c"), "has a and c")
        expected = ["body contains 'a'", "body contains 'c'"]
        assert result == expected


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
