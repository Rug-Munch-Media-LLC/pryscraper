"""Organic-result shapes: both DOM strategies, pagination, snippet fallback."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datasets.attention import serp
from datasets.attention.serp import text as text_mod
from tests.serp_fixtures import A_HTML, B_HTML, root


def test_organic_strategy_a_shapes() -> None:
    results = serp._extract_results(root(A_HTML), 10)
    assert [r["position"] for r in results] == [1]
    assert results[0] == {
        "position": 1,
        "title": "Bitcoin - Example",
        "url": "https://example.com/bitcoin",
        "snippet": "Bitcoin is a decentralized digital currency.",
    }


def test_organic_strategy_b_goto_url_absolute_and_snippet() -> None:
    results = serp._extract_results(root(B_HTML), 10)
    assert [r["title"] for r in results] == ["Raw Title"]
    assert results[0]["url"] == "https://www.google.com/goto?url=tok"
    assert results[0]["snippet"] == "Current DOM snippet."


def test_organic_respects_num_cap() -> None:
    assert len(serp._extract_results(root(A_HTML), 1)) == 1


def test_organic_empty_document() -> None:
    assert serp._extract_results(root("<html><body><p>none</p></body></html>"), 10) == []


def test_snippet_falls_back_through_selectors() -> None:
    block = root('<div><div class="IsZvec">fallback snippet</div></div>')
    assert text_mod._extract_snippet(block) == "fallback snippet"


def test_snippet_empty_when_no_selector_matches() -> None:
    assert text_mod._extract_snippet(root("<div><p>bare</p></div>")) == ""


def test_text_tolerates_broken_nodes() -> None:
    class Broken:
        def text_content(self) -> str:
            raise ValueError("broken")

    assert text_mod._text(object()) == ""
    assert text_mod._text(Broken()) == ""


def test_clean_google_url_shapes() -> None:
    clean = serp._clean_google_url
    assert clean("/url?q=https://example.com/x&sa=U") == "https://example.com/x"
    assert clean("https://direct.example.org/p") == "https://direct.example.org/p"
    assert clean("https://www.google.com/search?q=x") == ""
    assert clean("/url?q=") == ""
    assert clean("") == ""
