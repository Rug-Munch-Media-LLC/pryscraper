"""Pry — Scrapling-style adaptive selectors that survive page changes.

A selector engine that remembers where elements were found and can
relocate them after a site redesign, using surrounding context: text
content, tag name, attributes, and structural position (parent/sibling
shape). Pure HTML parsing — no HTTP.

DOM traversal lives in :mod:`pry.engine.selector_context`, candidate scoring in
:mod:`pry.engine.selector_match`, and page signatures in
:mod:`pry.engine.page_signature`; this module keeps the public API.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from pry.engine.page_signature import PageSignature
from pry.engine.selector_context import (
    ElementContext,
    attr_similarity,
    attrs_of,
    capture_context,
    norm_text,
    path_similarity,
    soup_of,
    structural_path,
    synthesize_selector,
)
from pry.engine.selector_match import find_best_match
from pry.engine.selector_match import MIN_TEXT_SIMILARITY as _MIN_TEXT_SIMILARITY
from pry.engine.selector_validate import _validate_selector

# Confidence levels.
_EXACT = 1.0
_RELOCATED = 0.5
_NOT_FOUND = 0.0

# Historical private aliases used by the existing tests/callers.
_soup = soup_of
_norm_text = norm_text
_attrs_of = attrs_of
_attr_similarity = attr_similarity
_structural_path = structural_path
_path_similarity = path_similarity
_find_best_match = find_best_match
_synthesize_selector = synthesize_selector
_ElementContext = ElementContext


class AdaptiveSelector:
    """A selector that remembers where elements were and can find them
    again if the page changes (Scrapling-style adaptive scraping)."""

    def __init__(self, html: str) -> None:
        self._soup = soup_of(html)
        self._contexts: dict[str, ElementContext] = {}
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
            self._contexts[name] = capture_context(node, selector)
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
            self._contexts[name] = capture_context(nodes[0], selector)
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
        if self._contexts.get(name) is None:
            return None
        return self._relocate_in_soup_from(name, soup_of(html))

    def _relocate_in_soup(self, name: str) -> str | None:
        if self._contexts.get(name) is None:
            self._confidence[name] = _NOT_FOUND
            return None
        return self._relocate_in_soup_from(name, self._soup)

    def _relocate_in_soup_from(self, name: str, soup: BeautifulSoup) -> str | None:
        """Relocate ``name`` inside ``soup`` and refresh the stored context."""
        ctx = self._contexts[name]
        best_node, best_score = find_best_match(soup, ctx)
        if best_node is None or best_score < _MIN_TEXT_SIMILARITY:
            self._confidence[name] = _NOT_FOUND
            return None
        # Update stored context to the new location.
        self._contexts[name] = capture_context(best_node, ctx.selector)
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
            name: ElementContext.from_dict(data)
            for name, data in state.items()
            if isinstance(data, dict)
        }

    def get_confidence(self, name: str) -> float:
        """How confident the selector is about a match for ``name``:
        1.0 = exact CSS match, 0.5 = relocated by context, 0.0 = not found."""
        return self._confidence.get(name, _NOT_FOUND)


def auto_relocate(old_html: str, new_html: str, selectors: dict[str, str]) -> dict[str, str]:
    """Given old HTML, new HTML, and a dict of named CSS selectors,
    return updated selectors that work on the new HTML.

    For each selector: if it still matches on the new HTML, keep it.
    Otherwise, capture context from the old HTML and relocate the
    element in the new HTML, then synthesize a new CSS selector for it.
    Selectors that cannot be relocated are dropped from the result.
    """
    old_soup = soup_of(old_html)
    new_soup = soup_of(new_html)
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
        ctx = capture_context(old_node, selector)

        best_node, best_score = find_best_match(new_soup, ctx)
        if best_node is None or best_score < _MIN_TEXT_SIMILARITY:
            continue

        updated[name] = synthesize_selector(best_node)

    return updated


__all__ = [
    "AdaptiveSelector",
    "PageSignature",
    "_ElementContext",
    "_attr_similarity",
    "_attrs_of",
    "_find_best_match",
    "_norm_text",
    "_path_similarity",
    "_structural_path",
    "_synthesize_selector",
    "auto_relocate",
]
