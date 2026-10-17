"""Tests for DOM-aware main-content selection (crawl4ai fit_markdown parity)."""

# SPDX-License-Identifier: MIT — part of Pry (https://git.rugmunch.io/RugMunchMedia/pryscraper)

from pry.engine.dom_prune import select_main_content

_NAV = "".join(f'<li><a href="/topic/{i}">Navigation link number {i}</a></li>' for i in range(40))
_PROSE = "The article body explains the story in ordinary sentences."


def _nav_heavy_page() -> str:
    return f"""<html><head><title>A story</title></head><body>
      <header><nav><ul>{_NAV}</ul></nav></header>
      <div class="sidebar"><a href="/promo">Promo</a><p>Sidebar blurb here.</p></div>
      <article class="post-content">
        <h1>The real headline</h1>
        <p>{_PROSE} Section one covers the background.</p>
        <p>{_PROSE} Section two covers the timeline.</p>
        <p>{_PROSE} Section three covers the people.</p>
        <p>{_PROSE} Section four covers the money.</p>
        <p>{_PROSE} Section five covers the outcome.</p>
      </article>
      <footer><a href="/legal">Legal</a> All rights reserved.</footer>
    </body></html>"""


def _link_farm_page() -> str:
    links = "".join(f'<a href="/out/{i}">Buy cheap thing {i}</a><br>' for i in range(60))
    return f'<html><body><div id="content">{links}</div></body></html>'


def test_nav_heavy_page_picks_article() -> None:
    out: dict[str, str] = {}
    html = select_main_content(_nav_heavy_page(), out=out)

    assert "The real headline" in html
    assert "Navigation link number 3" not in html
    assert "All rights reserved" not in html
    assert out["content_selector"].startswith("article")


def test_page_without_container_falls_back_to_body() -> None:
    page = "<html><body><p>First paragraph of prose.</p><p>Second paragraph of prose.</p></body></html>"
    out: dict[str, str] = {}

    html = select_main_content(page, out=out)

    assert "First paragraph of prose." in html
    assert "Second paragraph of prose." in html
    assert out["content_selector"] == "body"


def test_link_farm_is_rejected() -> None:
    out: dict[str, str] = {}

    html = select_main_content(_link_farm_page(), out=out)

    assert out["content_selector"] == "body"
    assert "Buy cheap thing 5" in html


def test_content_selector_is_populated() -> None:
    out: dict[str, str] = {}

    select_main_content(_nav_heavy_page(), out=out)

    assert out["content_selector"] == "article.post-content"


def test_empty_input_is_passthrough() -> None:
    out: dict[str, str] = {}

    assert select_main_content("", out=out) == ""


def _comments_heavy_page() -> str:
    comments = "".join(
        f"<p>Reader comment {i}: this take is wrong because of reasons {i}.</p>" for i in range(12)
    )
    return f"""<html><body>
      <div class="nav"><a href="/a">Home</a><a href="/b">About</a></div>
      <div class="content">
        <h1>Headline</h1>
        <p>Article paragraph one explains the facts plainly.</p>
        <p>Article paragraph two adds the context.</p>
        <p>Article paragraph three closes it out.</p>
      </div>
      <div class="comments"><h2>Comments</h2>{comments}</div>
    </body></html>"""


def test_comments_heavy_page_drops_reader_thread() -> None:
    out: dict[str, str] = {}

    html = select_main_content(_comments_heavy_page(), out=out)

    assert "Article paragraph two adds the context." in html
    assert "Reader comment 7" not in html
    assert out["content_selector"] == "div.content"
