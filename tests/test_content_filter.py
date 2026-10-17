# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.engine.content_filter — pure HTML/text processing.

Covers boilerplate pruning, essential filtering, main-content extraction,
minimal-markdown conversion, token estimation, chunk splitting, and the
full filter_and_chunk pipeline. No HTTP, no mocks.
"""

from __future__ import annotations

import pytest

from pry.engine.content_filter import (
    _split_chunks,
    estimate_tokens,
    extract_main_content,
    filter_and_chunk,
    filter_to_essential,
    html_to_minimal_markdown,
    prune_boilerplate,
)


class TestPruneBoilerplate:
    def test_removes_cookie_banner_by_class(self) -> None:
        html = '<div class="cookie-consent">Accept cookies</div><p>Real content</p>'
        out = prune_boilerplate(html)
        assert "Accept cookies" not in out
        assert "Real content" in out

    def test_removes_nav_by_id(self) -> None:
        html = '<div id="navbar">Home About</div><p>Body</p>'
        out = prune_boilerplate(html)
        assert "Home About" not in out
        assert "Body" in out

    def test_removes_social_share_widget(self) -> None:
        html = '<div class="social-share">Tweet</div><p>Keep me</p>'
        out = prune_boilerplate(html)
        assert "Tweet" not in out
        assert "Keep me" in out

    def test_keeps_plain_content(self) -> None:
        html = "<p>Nothing boilerplate here</p>"
        assert "Nothing boilerplate here" in prune_boilerplate(html)

    def test_removes_advertisement_container(self) -> None:
        html = '<div class="advertisement">Buy now</div><p>Article</p>'
        out = prune_boilerplate(html)
        assert "Buy now" not in out
        assert "Article" in out


class TestFilterToEssential:
    def test_strips_script_and_style(self) -> None:
        html = "<script>var x=1;</script><style>.a{}</style><p>Visible</p>"
        out = filter_to_essential(html)
        assert "var x=1" not in out
        assert ".a{}" not in out
        assert "Visible" in out

    def test_strips_nav_footer_header_aside(self) -> None:
        html = (
            "<nav>Nav</nav><header>Head</header><aside>Side</aside><footer>Foot</footer><p>Main</p>"
        )
        out = filter_to_essential(html)
        for gone in ("Nav", "Head", "Side", "Foot"):
            assert gone not in out
        assert "Main" in out

    def test_strips_form_controls(self) -> None:
        html = "<form><input value='x'><button>Go</button></form><p>Text</p>"
        out = filter_to_essential(html)
        assert "<form" not in out
        assert "<button" not in out
        assert "Text" in out

    def test_drops_empty_containers(self) -> None:
        html = "<div></div><div>   </div><p>Content</p>"
        out = filter_to_essential(html)
        assert out.count("<div>") == 0
        assert "Content" in out

    def test_image_only_container_is_emptied(self) -> None:
        # The <img> itself has no text and no nested <img>, so the empty-
        # container sweep decomposes it; the wrapper div is then empty too.
        html = '<div><img src="a.png" alt="a"></div>'
        out = filter_to_essential(html)
        assert "<img" not in out
        assert out == "<div></div>"


class TestExtractMainContent:
    def test_prefers_article_tag(self) -> None:
        body = "A" * 150
        html = f"<article><p>{body}</p></article><div><p>short</p></div>"
        result = extract_main_content(html)
        assert body in result["main_text"]
        assert result["title"] == ""

    def test_extracts_title(self) -> None:
        html = "<html><head><title>My Page</title></head><body><p>x</p></body></html>"
        assert extract_main_content(html)["title"] == "My Page"

    def test_fallback_picks_largest_text_block(self) -> None:
        big = "B" * 200
        html = f"<div><p>{big}</p></div><div><p>tiny</p></div>"
        result = extract_main_content(html)
        assert big in result["main_text"]

    def test_reduction_pct_is_bounded(self) -> None:
        html = "<article><p>" + ("C" * 100) + "</p></article>"
        result = extract_main_content(html)
        assert 0.0 <= result["reduction_pct"] <= 100.0

    def test_empty_html_returns_empty_text(self) -> None:
        result = extract_main_content("")
        assert result["main_text"] == ""
        assert result["title"] == ""


class TestHtmlToMinimalMarkdown:
    def test_headings(self) -> None:
        md = html_to_minimal_markdown("<h1>Title</h1><h2>Sub</h2>")
        assert md == "# Title\n\n## Sub"

    def test_paragraph(self) -> None:
        assert html_to_minimal_markdown("<p>Hello world</p>") == "Hello world"

    def test_list_items(self) -> None:
        md = html_to_minimal_markdown("<ul><li>One</li><li>Two</li></ul>")
        assert md == "- One\n\n- Two"

    def test_bold_and_italic(self) -> None:
        md = html_to_minimal_markdown("<p><strong>B</strong> and <em>I</em></p>")
        assert md == "**B** and *I*"

    def test_inline_code(self) -> None:
        assert html_to_minimal_markdown("<p><code>x=1</code></p>") == "`x=1`"

    def test_links_included_by_default(self) -> None:
        md = html_to_minimal_markdown('<p><a href="https://e.com">Link</a></p>')
        assert md == "[Link](https://e.com)"

    def test_links_excluded(self) -> None:
        md = html_to_minimal_markdown(
            '<p><a href="https://e.com">Link</a></p>', include_links=False
        )
        assert md == "Link"

    def test_images_excluded_by_default(self) -> None:
        md = html_to_minimal_markdown('<p><img src="a.png" alt="pic"></p>')
        assert md == ""

    def test_images_included(self) -> None:
        md = html_to_minimal_markdown('<p><img src="a.png" alt="pic"></p>', include_images=True)
        assert md == "![pic](a.png)"

    def test_image_default_alt(self) -> None:
        md = html_to_minimal_markdown('<p><img src="a.png"></p>', include_images=True)
        assert md == "![image](a.png)"

    def test_empty_heading_dropped(self) -> None:
        assert html_to_minimal_markdown("<h1></h1><p>Body</p>") == "Body"

    def test_blockquote(self) -> None:
        md = html_to_minimal_markdown("<blockquote>Quoted</blockquote>")
        assert md == "> Quoted"

    def test_pre_code_block(self) -> None:
        md = html_to_minimal_markdown("<pre>print(1)</pre>")
        assert md == "```\nprint(1)\n```"

    def test_hr(self) -> None:
        assert html_to_minimal_markdown("<hr>") == "---"

    def test_table(self) -> None:
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        md = html_to_minimal_markdown(html)
        # Each table row is a separate block joined by blank lines.
        assert md == "| A | B |\n\n|---|---|\n\n| 1 | 2 |"

    def test_br_collapses_to_space(self) -> None:
        # _inline_to_md emits "\n" for <br>, but the whitespace-collapse
        # regex then folds it into a single space.
        md = html_to_minimal_markdown("<p>a<br>b</p>")
        assert md == "a b"

    def test_max_line_length_wraps(self) -> None:
        long_text = "word " * 30
        md = html_to_minimal_markdown(f"<p>{long_text}</p>", max_line_length=20)
        assert all(len(line) <= 20 for line in md.split("\n"))

    def test_max_line_length_keeps_heading_intact(self) -> None:
        md = html_to_minimal_markdown("<h1>" + ("x" * 50) + "</h1>", max_line_length=10)
        assert md == "# " + ("x" * 50)


class TestEstimateTokens:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("", 0), ("abcd", 1), ("abcdefgh", 2), ("a" * 100, 25)],
    )
    def test_estimate(self, text: str, expected: int) -> None:
        assert estimate_tokens(text) == expected


class TestSplitChunks:
    def test_empty_returns_empty(self) -> None:
        assert _split_chunks("", 100, 10) == []

    def test_single_short_paragraph(self) -> None:
        expected = ["hello"]
        assert _split_chunks("hello", 100, 10) == expected

    def test_splits_on_paragraph_boundary(self) -> None:
        text = "A" * 60 + "\n\n" + "B" * 60
        chunks = _split_chunks(text, 100, 0)
        assert len(chunks) == 2
        assert chunks[0] == "A" * 60
        assert chunks[1] == "B" * 60

    def test_overlap_carries_tail(self) -> None:
        text = "A" * 60 + "\n\n" + "B" * 60
        chunks = _split_chunks(text, 100, 10)
        assert chunks[1].startswith("A" * 10)

    def test_oversized_paragraph_kept_whole(self) -> None:
        text = "X" * 250
        chunks = _split_chunks(text, 100, 0)
        expected = ["X" * 250]
        assert chunks == expected


class TestFilterAndChunk:
    def test_pipeline_shape(self) -> None:
        html = "<article><h1>Title</h1><p>" + ("word " * 50) + "</p></article>"
        result = filter_and_chunk(html, chunk_size=100, chunk_overlap=10)
        expected = {
            "markdown",
            "chunks",
            "total_tokens",
            "chunks_count",
            "reduction_pct",
        }
        assert set(result) == expected
        assert result["chunks_count"] == len(result["chunks"])
        assert result["total_tokens"] == estimate_tokens(result["markdown"])

    def test_strips_boilerplate_in_pipeline(self) -> None:
        html = "<nav>Menu</nav><article><p>Real body text here</p></article>"
        result = filter_and_chunk(html)
        assert "Menu" not in result["markdown"]
        assert "Real body text here" in result["markdown"]

    def test_reduction_pct_non_negative(self) -> None:
        html = "<article><p>tiny</p></article>"
        assert filter_and_chunk(html)["reduction_pct"] >= 0.0

    def test_empty_html(self) -> None:
        result = filter_and_chunk("")
        assert result["markdown"] == ""
        assert result["chunks"] == []
        assert result["chunks_count"] == 0
