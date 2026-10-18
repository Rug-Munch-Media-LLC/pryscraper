"""Pry — DOM-aware main-content selection (crawl4ai ``fit_markdown`` parity).

Scores candidate containers on rendered text volume, paragraph count, link
density and class/id hints, then hands the winning subtree to the extractor.
Script/style-like nodes are dropped before scoring so only visible text counts.

``select_main_content`` is the one entry point: it prunes an HTML document and,
when an ``out`` mapping is supplied, records the winning selector for
debuggability (``metadata.content_selector``).
"""

# SPDX-License-Identifier: MIT — part of Pry (https://git.rugmunch.io/RugMunchMedia/pryscraper)

from __future__ import annotations

import re
from typing import Any

import lxml.html

_POSITIVE = re.compile(r"(?i)(article|content|main|post|story|entry|blog|prose|body-text)")
_NEGATIVE = re.compile(
    r"(?i)(nav|sidebar|side-bar|footer|comment|promo|cookie|menu|advert|sponsor|"
    r"breadcrumb|share|related|widget|banner|modal|popup|subscribe|newsletter|"
    r"social|toolbar|pagination)"
)
_CONTAINERS = frozenset({"article", "main", "section", "div", "td", "li"})
_DROP = ("script", "style", "noscript", "template", "svg", "iframe")
_MAX_TEXT = 2000
_MIN_TEXT = 40


def _text_len(el: Any) -> int:
    return len(" ".join(el.text_content().split()))


def _link_density(el: Any, text_len: int) -> float:
    """Share of visible characters that live inside anchors (0.0-1.0)."""
    linked = sum(_text_len(a) for a in el.iter("a"))
    return linked / text_len if text_len else 1.0


def _hint(el: Any) -> float:
    """Class/id semantics: article-like containers up, chrome-like ones down."""
    attrs = f"{el.get('class') or ''} {el.get('id') or ''}"
    score = 25.0 if el.tag in ("article", "main") or _POSITIVE.search(attrs) else 0.0
    return score - 50.0 if _NEGATIVE.search(attrs) else score


def _score(el: Any, depth: int) -> float:
    """Container score; negative means 'not a plausible main content root'."""
    text = _text_len(el)
    if text < _MIN_TEXT:
        return -1.0
    paragraphs = len(el.xpath(".//p[normalize-space()]"))
    volume = min(text, _MAX_TEXT) / 20.0
    structure = min(paragraphs, 20) * 2.5
    density_penalty = _link_density(el, text) * 120.0
    return volume + structure + _hint(el) + depth * 1.5 - density_penalty


def _selector(el: Any) -> str:
    """Readable ``tag.class`` / ``tag#id`` handle for debugging."""
    classes = (el.get("class") or "").split()
    if classes:
        return f"{el.tag}.{classes[0]}"
    if el.get("id"):
        return f"{el.tag}#{el.get('id')}"
    return str(el.tag)


def _candidates(doc: Any):
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in _CONTAINERS:
            yield el


def _drop_boilerplate(doc: Any) -> None:
    """Remove script/style-like subtrees, keeping their tail text.

    ``drop_tree`` belongs to the *element* being removed (``HtmlMixin``), not
    to its parent, and it merges the dropped node's tail into the preceding
    sibling/parent. Detached nodes (already removed, or the document root)
    have no parent and are skipped: dropping the root is unsupported.
    """
    for tag in _DROP:
        for el in list(doc.iter(tag)):
            if el.getparent() is not None:
                el.drop_tree()


def select_main_content(html: str, out: dict[str, Any] | None = None) -> str:
    """Return the HTML of the best-scoring content container.

    Falls back to the whole ``<body>`` when no candidate scores above zero.
    ``out`` — optional sink receiving ``content_selector`` (tag/class handle).
    """
    if not html or not html.strip():
        return html
    try:
        doc = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return html
    _drop_boilerplate(doc)

    best, best_score = None, 0.0
    for depth, el in enumerate(_candidates(doc)):
        score = _score(el, depth % 20)
        if score > best_score:
            best, best_score = el, score

    if best is None:
        if out is not None:
            out["content_selector"] = "body"
        # Nothing won: hand back the untouched document. A body-only
        # re-serialization makes trafilatura drop short pages entirely.
        return html

    if out is not None:
        out["content_selector"] = _selector(best)
    return lxml.html.tostring(best, encoding="unicode", method="html")


def finalize_document(result: dict[str, Any], url: str = "", include_images: bool = False) -> dict:
    """Normalize markdown and surface ``content_selector`` in the metadata."""
    from pry.engine.markdown_quality import finalize_markdown

    result = finalize_markdown(result, url, include_images)
    if result.get("content_selector"):
        result["metadata"]["content_selector"] = result["content_selector"]
    return result
