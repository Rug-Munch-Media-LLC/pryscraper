# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for markdown generation strategies."""

from markdown_gen import BM25ContentFilter, DefaultMarkdownGenerator, PruningContentFilter


def test_pruning_filter_removes_boilerplate() -> None:
    content = "Welcome\n# Navigation\nHome\nAbout\n## Main Content\nThis is real content.\nFooter\nCopyright 2024"
    filter_ = PruningContentFilter()
    result = filter_.filter(content)
    assert "Navigation" not in result or "Navigation" not in result
    assert "Main Content" in result


def test_pruning_score() -> None:
    content = "# Title\n## Section\nReal content here.\nFooter"
    filter_ = PruningContentFilter()
    score = filter_.score(content)
    assert "boilerplate_ratio" in score
    assert "quality" in score


def test_bm25_filter() -> None:
    content = "# Prices\nOur product costs $10.\n# Contact\nCall us at 555-0100.\n# Shipping\nFree shipping over $50."
    filter_ = BM25ContentFilter(threshold=0.5)
    result = filter_.filter(content, "product pricing cost")
    assert "Prices" in result
    assert "Contact" not in result


def test_bm25_no_query() -> None:
    content = "# Test\nContent"
    filter_ = BM25ContentFilter()
    result = filter_.filter(content, "")
    assert result == content


def test_default_generator_raw() -> None:
    gen = DefaultMarkdownGenerator()
    result = gen.generate("# Hello\nWorld")
    assert "raw_markdown" in result


def test_default_generator_with_pruning() -> None:
    gen = DefaultMarkdownGenerator(content_filter=PruningContentFilter())
    result = gen.generate("# Hello\nWorld\nFooter\nCopyright")
    assert "fit_markdown" in result
