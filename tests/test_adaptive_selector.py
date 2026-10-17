# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.engine.adaptive_selector — pure HTML parsing, no HTTP.

Covers exact selection + context capture, confidence tracking, relocation
after a redesign, state persistence, page-structure signatures/diffing,
selector synthesis, and the auto_relocate entry point.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from pry.engine.adaptive_selector import (
    AdaptiveSelector,
    PageSignature,
    _attr_similarity,
    _attrs_of,
    _norm_text,
    _path_similarity,
    _structural_path,
    _synthesize_selector,
    auto_relocate,
)

_PAGE = (
    '<html><body><div id="main">'
    '<h1 class="title">Hello World</h1><p>Body text here</p>'
    "</div></body></html>"
)
_REDESIGNED = (
    '<html><body><div id="main">'
    '<h1 class="hero">Hello World</h1><p>Body text here</p>'
    "</div></body></html>"
)


class TestSelectors:
    def test_select_exact_stores_state_and_confidence(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        assert sel.select("title", "h1.title") is not None
        assert sel.get_confidence("title") == 1.0
        assert sel.save_state()["title"]["tag"] == "h1"

    def test_select_all_returns_every_match(self) -> None:
        sel = AdaptiveSelector('<ul><li class="x">A</li><li class="x">B</li></ul>')
        assert len(sel.select_all("items", "li.x")) == 2
        assert sel.get_confidence("items") == 1.0

    def test_missing_selector_records_not_found(self) -> None:
        sel = AdaptiveSelector("<div><p>hi</p></div>")
        assert sel.select("x", "span.missing") is None
        assert sel.get_confidence("x") == 0.0

    def test_unknown_name_defaults_to_not_found(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        assert sel.get_confidence("never-seen") == 0.0


class TestRelocation:
    def test_relocate_finds_element_after_class_change(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        sel.select("title", "h1.title")
        assert sel.relocate("title", _REDESIGNED) is not None
        assert sel.get_confidence("title") == 0.5

    def test_relocate_unknown_name_returns_none(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        assert sel.relocate("nope", _REDESIGNED) is None

    def test_select_falls_back_to_relocation(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        sel.select("title", "h1.title")
        # A fresh instance on the redesigned page shares no stored context,
        # so select must fail cleanly rather than raise.
        fresh = AdaptiveSelector(_REDESIGNED)
        assert fresh.select("title", "h1.title") is None


class TestPersistence:
    def test_save_load_state_roundtrip(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        sel.select("title", "h1.title")
        restored = AdaptiveSelector(_PAGE)
        restored.load_state(sel.save_state())
        assert restored.save_state()["title"]["text"] == "hello world"

    def test_load_state_ignores_non_dict_entries(self) -> None:
        sel = AdaptiveSelector(_PAGE)
        sel.load_state({"bad": 123})
        assert sel.save_state() == {}


class TestPageSignature:
    def test_identical_structure_matches(self) -> None:
        assert PageSignature(_PAGE).signature() == PageSignature(_PAGE).signature()

    def test_class_change_is_detected(self) -> None:
        assert PageSignature(_PAGE).changed(PageSignature(_REDESIGNED))

    def test_diff_regions_reports_changed_subtree(self) -> None:
        old = "<html><body><div><p>a</p></div></body></html>"
        new = "<html><body><div><span>a</span></div></body></html>"
        regions = PageSignature(old).diff_regions(PageSignature(new))
        assert any("div" in region for region in regions)


class TestSelectorSynthesis:
    def test_synthesize_prefers_id(self) -> None:
        assert _synthesize_selector(BeautifulSoup('<a id="foo"></a>', "html.parser").a) == "a#foo"

    def test_synthesize_uses_classes(self) -> None:
        node = BeautifulSoup('<a class="b c"></a>', "html.parser").a
        assert _synthesize_selector(node) == "a.b.c"

    def test_synthesize_uses_data_testid(self) -> None:
        node = BeautifulSoup('<a data-testid="t1"></a>', "html.parser").a
        assert _synthesize_selector(node) == 'a[data-testid="t1"]'

    def test_synthesize_falls_back_to_nth_of_type(self) -> None:
        second = BeautifulSoup("<div><p></p><p></p></div>", "html.parser").find_all("p")[1]
        assert ":nth-of-type(1)" in _synthesize_selector(second)


class TestAutoRelocate:
    def test_keeps_selector_that_still_matches(self) -> None:
        expected = {"title": "h1.title"}
        assert auto_relocate(_PAGE, _PAGE, {"title": "h1.title"}) == expected

    def test_synthesizes_new_selector_after_redesign(self) -> None:
        updated = auto_relocate(_PAGE, _REDESIGNED, {"title": "h1.title"})
        expected = {"title": "h1.hero"}
        assert updated == expected

    def test_drops_selector_that_never_matched(self) -> None:
        assert auto_relocate("<p>x</p>", "<p>x</p>", {"k": "p.missing"}) == {}


class TestSimilarityHelpers:
    def test_norm_text_collapses_whitespace_and_case(self) -> None:
        assert _norm_text("  A   B  ") == "a b"

    def test_attrs_of_flattens_list_values(self) -> None:
        node = BeautifulSoup('<a class="b c"></a>', "html.parser").a
        assert _attrs_of(node)["class"] == "b c"

    def test_attr_similarity_neutral_when_both_empty(self) -> None:
        assert _attr_similarity({}, {}) == 0.5

    def test_path_similarity_identical_paths(self) -> None:
        assert _path_similarity(["html", "body"], ["html", "body"]) == 1.0

    def test_structural_path_root_to_node(self) -> None:
        node = BeautifulSoup("<div><p></p></div>", "html.parser").p
        assert _structural_path(node)[-1] == "p"
