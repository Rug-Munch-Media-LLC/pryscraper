# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for SEO content monitor."""

from pry.actors.seo_monitor import (
    _count_words,
    _get_headings,
    _get_meta_from_html,
    _get_title_from_html,
    _has_schema,
)


def test_get_title_from_html() -> None:
    html = "<html><head><title>My SEO Title</title></head><body></body></html>"
    assert _get_title_from_html(html) == "My SEO Title"


def test_get_meta_from_html() -> None:
    html = '<meta name="description" content="Test description here" />'
    desc = _get_meta_from_html(html, "description")
    assert desc == "Test description here"


def test_count_words() -> None:
    html = "<p>Hello world this is a test</p>"
    assert _count_words(html) == 6


def test_get_headings() -> None:
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(
        "<html><body><h1>Main Title</h1><h2>Sub One</h2><h2>Sub Two</h2></body></html>"
    )
    h1s = _get_headings(tree, "h1")
    assert h1s == ["Main Title"]
    h2s = _get_headings(tree, "h2")
    assert len(h2s) == 2


def test_has_schema() -> None:
    html = '<script type="application/ld+json">{"@context": "https://schema.org"}</script>'
    assert _has_schema(html) is True


def test_has_no_schema() -> None:
    html = "<html><body><p>No schema here</p></body></html>"
    assert _has_schema(html) is False
