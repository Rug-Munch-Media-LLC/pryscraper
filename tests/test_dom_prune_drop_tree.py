"""Regression: boilerplate pruning must call ``el.drop_tree()`` (P0 500/502).

``lxml.html.HtmlMixin.drop_tree`` is a method of the element being removed and
takes no arguments. Calling ``parent.drop_tree(el)`` raised ``TypeError`` on
every page containing script/style/noscript/template/svg/iframe.
"""

# SPDX-License-Identifier: MIT — part of Pry (https://git.rugmunch.io/RugMunchMedia/pryscraper)

import lxml.html

from pry.engine.dom_prune import _drop_boilerplate, select_main_content

_PROSE = "The article body explains the story in ordinary sentences."

_FIXTURE = f"""<html><head><title>A story</title></head><body>
  <article class="post">
    <h1>The real headline</h1>
    <p>{_PROSE} Section one covers the background in detail.</p>
    <script>var leakedScript = 1;</script>Tail after script survives.
    <style>.leakedStyle {{ color: red; }}</style>Tail after style survives.
    <noscript><p>Enable JavaScript to view this noscript block.</p></noscript>
    <template><p>Template placeholder body that must not be scored.</p></template>
    <svg><rect width="10" height="10"></rect></svg>Tail after svg survives.
    <iframe src="https://ads.example/embed"></iframe>Tail after iframe survives.
    <p>{_PROSE} Section two covers the timeline in detail.</p>
  </article>
</body></html>"""


def test_boilerplate_nodes_are_dropped_and_tails_survive() -> None:
    out: dict[str, str] = {}

    html = select_main_content(_FIXTURE, out=out)

    for leaked in (
        "leakedScript",
        "leakedStyle",
        "Enable JavaScript",
        "Template placeholder",
        "rect width",
        "ads.example",
    ):
        assert leaked not in html
    for tail in (
        "Tail after script survives.",
        "Tail after style survives.",
        "Tail after svg survives.",
        "Tail after iframe survives.",
    ):
        assert tail in html
    assert out["content_selector"] == "article.post"
    assert "The real headline" in html
    assert "Section one covers the background" in html
    assert "Section two covers the timeline" in html


def test_drop_boilerplate_keeps_tail_text_before_sibling() -> None:
    doc = lxml.html.fromstring("<div><p>before</p><script>x</script>tail<span>after</span></div>")

    _drop_boilerplate(doc)

    assert doc.xpath("//script") == []
    assert "tail" in doc.text_content()
    assert "after" in doc.text_content()


def test_root_level_script_document_does_not_raise() -> None:
    out: dict[str, str] = {}

    html = select_main_content("<script>var x = 1;</script>", out=out)

    assert "var x = 1;" in html
    assert out["content_selector"] == "body"
