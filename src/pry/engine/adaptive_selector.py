"""Pry — Scrapling-style adaptive selectors that survive page changes.

A selector engine that remembers where elements were found and can
relocate them after a site redesign, using surrounding context: text
content, tag name, attributes, and structural position (parent/sibling
shape). Pure HTML parsing — no HTTP.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

from pry.engine.schema_extract import _validate_selector

# Confidence levels.
_EXACT = 1.0
_RELOCATED = 0.5
_NOT_FOUND = 0.0

# Minimum fuzzy text similarity to accept a relocation candidate.
_MIN_TEXT_SIMILARITY = 0.4

# How many candidate elements to score during relocation (perf cap).
_MAX_CANDIDATES = 400


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _attrs_of(node: Tag) -> dict[str, str]:
    """Flatten a tag's attributes to str -> str (bs4 may give lists)."""
    out: dict[str, str] = {}
    for key, value in node.attrs.items():
        if isinstance(value, (list, tuple)):
            out[key] = " ".join(str(v) for v in value)
        else:
            out[key] = str(value)
    return out


def _attr_similarity(a: dict[str, str], b: dict[str, str]) -> float:
    """Jaccard-ish similarity over attribute key=value pairs."""
    if not a and not b:
        return 0.5  # no attributes on either side: neutral signal
    keys = set(a) | set(b)
    if not keys:
        return 0.5
    hits = sum(1 for k in keys if a.get(k) == b.get(k) and a.get(k) is not None)
    return hits / len(keys)


def _structural_path(node: Tag) -> list[str]:
    """Tag names from root down to (and including) this node."""
    names: list[str] = []
    current: Tag | None = node
    while current is not None and current.name:
        names.append(current.name)
        current = current.parent if isinstance(current.parent, Tag) else None
    names.reverse()
    return names


def _path_similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class _ElementContext:
    """Everything we remember about where an element lived."""

    selector: str
    tag: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    text: str = ""
    parent_tag: str = ""
    parent_attrs: dict[str, str] = field(default_factory=dict)
    sibling_tags: list[str] = field(default_factory=list)
    sibling_text: str = ""
    path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "tag": self.tag,
            "attrs": self.attrs,
            "text": self.text,
            "parent_tag": self.parent_tag,
            "parent_attrs": self.parent_attrs,
            "sibling_tags": self.sibling_tags,
            "sibling_text": self.sibling_text,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _ElementContext:
        return cls(
            selector=data.get("selector", ""),
            tag=data.get("tag", ""),
            attrs=dict(data.get("attrs", {})),
            text=data.get("text", ""),
            parent_tag=data.get("parent_tag", ""),
            parent_attrs=dict(data.get("parent_attrs", {})),
            sibling_tags=list(data.get("sibling_tags", [])),
            sibling_text=data.get("sibling_text", ""),
            path=list(data.get("path", [])),
        )


def _capture_context(node: Tag, selector: str) -> _ElementContext:
    """Snapshot the surroundings of a matched element."""
    parent = node.parent if isinstance(node.parent, Tag) else None
    siblings = [s for s in node.find_previous_siblings() if isinstance(s, Tag)]
    prev = siblings[0] if siblings else None
    return _ElementContext(
        selector=selector,
        tag=node.name or "",
        attrs=_attrs_of(node),
        text=_norm_text(node.get_text(" ", strip=True))[:500],
        parent_tag=parent.name if parent else "",
        parent_attrs=_attrs_of(parent) if parent else {},
        sibling_tags=[s.name or "" for s in siblings[:5]],
        sibling_text=_norm_text(prev.get_text(" ", strip=True))[:200] if prev else "",
        path=_structural_path(node),
    )


def _score_candidate(node: Tag, ctx: _ElementContext) -> float:
    """Score how likely a candidate node is the relocated element (0..1)."""
    score = 0.0
    weight = 0.0

    # Tag name match.
    weight += 1.0
    if ctx.tag and node.name == ctx.tag:
        score += 1.0

    # Attribute similarity.
    weight += 1.0
    score += _attr_similarity(_attrs_of(node), ctx.attrs)

    # Text similarity (fuzzy).
    weight += 1.5
    node_text = _norm_text(node.get_text(" ", strip=True))[:500]
    if ctx.text and node_text:
        ratio = difflib.SequenceMatcher(None, ctx.text, node_text).ratio()
        score += ratio
    elif not ctx.text and not node_text:
        score += 1.0  # both empty: consistent

    # Structural path similarity.
    weight += 1.0
    score += _path_similarity(_structural_path(node), ctx.path)

    # Parent tag/attrs.
    weight += 0.5
    parent = node.parent if isinstance(node.parent, Tag) else None
    if parent is not None and ctx.parent_tag and parent.name == ctx.parent_tag:
        score += 0.5
        score += 0.5 * _attr_similarity(_attrs_of(parent), ctx.parent_attrs)

    # Previous-sibling text.
    weight += 0.5
    prev_sibs = [s for s in node.find_previous_siblings() if isinstance(s, Tag)]
    if prev_sibs and ctx.sibling_text:
        prev_text = _norm_text(prev_sibs[0].get_text(" ", strip=True))[:200]
        if prev_text and difflib.SequenceMatcher(None, ctx.sibling_text, prev_text).ratio() > 0.6:
            score += 0.5

    return score / weight if weight else 0.0


def _find_best_match(soup: BeautifulSoup, ctx: _ElementContext) -> tuple[Tag | None, float]:
    """Scan candidate elements and return the highest-scoring match."""
    candidates = soup.find_all(ctx.tag) if ctx.tag else soup.find_all(True)
    if not candidates and ctx.tag:
        # Remembered tag may have changed; scan everything.
        candidates = soup.find_all(True)
    best: Tag | None = None
    best_score = 0.0
    scanned = 0
    for node in candidates:
        if not isinstance(node, Tag):
            continue
        scanned += 1
        if scanned > _MAX_CANDIDATES:
            break
        node_score = _score_candidate(node, ctx)
        if node_score > best_score:
            best = node
            best_score = node_score
    return best, best_score


class AdaptiveSelector:
    """A selector that remembers where elements were and can find them
    again if the page changes (Scrapling-style adaptive scraping)."""

    def __init__(self, html: str) -> None:
        self._soup = _soup(html)
        self._contexts: dict[str, _ElementContext] = {}
        self._confidence: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, name: str, selector: str, context: dict | None = None) -> str | None:
        """Select an element by CSS selector. On success, store the
        selector + surrounding context for later relocation. On failure,
        try to relocate using previously stored context.

        Raises :class:`InvalidRequestError` (HTTP 400) for an unsafe selector.
        """
        _validate_selector(selector, field="selector")
        node = self._soup.select_one(selector)
        if node is not None:
            self._contexts[name] = _capture_context(node, selector)
            self._confidence[name] = _EXACT
            return str(node)

        relocated = self._relocate_in_soup(name)
        return relocated

    def select_all(self, name: str, selector: str, context: dict | None = None) -> list[str]:
        """Select multiple elements by CSS selector. Stores context from
        the first match for later relocation.

        Raises :class:`InvalidRequestError` (HTTP 400) for an unsafe selector.
        """
        _validate_selector(selector, field="selector")
        nodes = self._soup.select(selector)
        if nodes:
            self._contexts[name] = _capture_context(nodes[0], selector)
            self._confidence[name] = _EXACT
            return [str(n) for n in nodes]
        relocated = self._relocate_in_soup(name)
        return [relocated] if relocated else []

    # ------------------------------------------------------------------
    # Relocation
    # ------------------------------------------------------------------

    def relocate(self, name: str, html: str) -> str | None:
        """Given new HTML, try to find the element previously stored at
        ``name`` using its captured context (text similarity, tag name,
        attribute similarity, structural position)."""
        ctx = self._contexts.get(name)
        if ctx is None:
            return None
        soup = _soup(html)
        best_node, best_score = _find_best_match(soup, ctx)
        if best_node is None or best_score < _MIN_TEXT_SIMILARITY:
            self._confidence[name] = _NOT_FOUND
            return None
        # Update stored context to the new location.
        self._contexts[name] = _capture_context(best_node, ctx.selector)
        self._confidence[name] = _RELOCATED
        return str(best_node)

    def _relocate_in_soup(self, name: str) -> str | None:
        ctx = self._contexts.get(name)
        if ctx is None:
            self._confidence[name] = _NOT_FOUND
            return None
        best_node, best_score = _find_best_match(self._soup, ctx)
        if best_node is None or best_score < _MIN_TEXT_SIMILARITY:
            self._confidence[name] = _NOT_FOUND
            return None
        self._contexts[name] = _capture_context(best_node, ctx.selector)
        self._confidence[name] = _RELOCATED
        return str(best_node)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self) -> dict:
        """Save all stored selectors + context as a JSON-serializable dict."""
        return {name: ctx.to_dict() for name, ctx in self._contexts.items()}

    def load_state(self, state: dict) -> None:
        """Load previously saved state."""
        self._contexts = {
            name: _ElementContext.from_dict(data)
            for name, data in state.items()
            if isinstance(data, dict)
        }

    def get_confidence(self, name: str) -> float:
        """How confident the selector is about a match for ``name``:
        1.0 = exact CSS match, 0.5 = relocated by context, 0.0 = not found."""
        return self._confidence.get(name, _NOT_FOUND)


class PageSignature:
    """A structural signature of a page for change detection.

    Hashes the tag tree while ignoring text content, so content edits do
    not count as structural changes but layout/DOM changes do.
    """

    def __init__(self, html: str) -> None:
        self._soup = _soup(html)

    def signature(self) -> str:
        """A hash of the page structure (tag tree, ignoring text)."""
        return hashlib.sha256(self._tree_repr(self._soup).encode()).hexdigest()

    def changed(self, other: PageSignature) -> bool:
        """Whether the page structure changed relative to ``other``."""
        return self.signature() != other.signature()

    def diff_regions(self, other: PageSignature) -> list[str]:
        """CSS-selector-ish paths of subtrees that changed between the
        two pages (e.g. ``html > body > div#main > ul``)."""
        regions: list[str] = []
        self._diff_walk(self._soup, other._soup, [], regions)
        return regions

    # -- internals -----------------------------------------------------

    def _tree_repr(self, node: Any) -> str:
        """Recursive structural representation, text ignored."""
        if not isinstance(node, Tag):
            return ""
        attrs = _attrs_of(node)
        attr_repr = ",".join(f"{k}={attrs[k]}" for k in sorted(attrs))
        children = "".join(
            self._tree_repr(child) for child in node.children if isinstance(child, Tag)
        )
        return f"<{node.name}[{attr_repr}]{children}>"

    def _diff_walk(
        self,
        a: Any,
        b: Any,
        path: list[str],
        out: list[str],
    ) -> None:
        if not isinstance(a, Tag) or not isinstance(b, Tag):
            return
        if self._tree_repr(a) != self._tree_repr(b):
            region = " > ".join([*path, a.name or "?"])
            if region not in out:
                out.append(region)
            # Recurse to find finer-grained changed regions.
            a_children = [c for c in a.children if isinstance(c, Tag)]
            b_children = [c for c in b.children if isinstance(c, Tag)]
            if len(a_children) == len(b_children):
                for ca, cb in zip(a_children, b_children, strict=False):
                    self._diff_walk(ca, cb, [*path, a.name or "?"], out)


def auto_relocate(old_html: str, new_html: str, selectors: dict[str, str]) -> dict[str, str]:
    """Given old HTML, new HTML, and a dict of named CSS selectors,
    return updated selectors that work on the new HTML.

    For each selector: if it still matches on the new HTML, keep it.
    Otherwise, capture context from the old HTML and relocate the
    element in the new HTML, then synthesize a new CSS selector for it.
    Selectors that cannot be relocated are dropped from the result.
    """
    old_soup = _soup(old_html)
    new_soup = _soup(new_html)
    updated: dict[str, str] = {}

    for name, selector in selectors.items():
        # Still valid? Keep as-is.
        if new_soup.select_one(selector) is not None:
            updated[name] = selector
            continue

        # Capture context from the old page.
        old_node = old_soup.select_one(selector)
        if old_node is None:
            continue  # never matched; nothing to relocate
        ctx = _capture_context(old_node, selector)

        best_node, best_score = _find_best_match(new_soup, ctx)
        if best_node is None or best_score < _MIN_TEXT_SIMILARITY:
            continue

        updated[name] = _synthesize_selector(best_node)

    return updated


def _synthesize_selector(node: Tag) -> str:
    """Build a reasonably specific CSS selector for a node."""
    attrs = _attrs_of(node)
    if node.get("id"):
        return f"{node.name}#{node['id']}"
    classes = node.get("class")
    if isinstance(classes, (list, tuple)) and classes:
        cls = ".".join(str(c) for c in classes[:2])
        return f"{node.name}.{cls}"
    if "data-testid" in attrs:
        return f'{node.name}[data-testid="{attrs["data-testid"]}"]'
    if "name" in attrs:
        return f'{node.name}[name="{attrs["name"]}"]'
    # Fall back to nth-of-type within parent.
    parent = node.parent if isinstance(node.parent, Tag) else None
    if parent is not None:
        same_tag = [c for c in parent.children if isinstance(c, Tag) and c.name == node.name]
        index = same_tag.index(node) + 1 if node in same_tag else 1
        parent_sel = (
            _synthesize_selector(parent)
            if parent.name not in ("[document]", "html")
            else parent.name
        )
        return f"{parent_sel} > {node.name}:nth-of-type({index})"
    return node.name or "*"
