"""Structural page signatures for change detection.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import hashlib
from typing import Any

from bs4 import BeautifulSoup, Tag

from pry.engine.selector_context import attrs_of, soup_of


class PageSignature:
    """A structural signature of a page for change detection.

    Hashes the tag tree while ignoring text content, so content edits do
    not count as structural changes but layout/DOM changes do.
    """

    def __init__(self, html: str) -> None:
        self._soup = soup_of(html)

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

    def _tree_repr(self, node: Any) -> str:
        """Recursive structural representation, text ignored."""
        if not isinstance(node, Tag):
            return ""
        attrs = attrs_of(node)
        attr_repr = ",".join(f"{k}={attrs[k]}" for k in sorted(attrs))
        children = "".join(
            self._tree_repr(child) for child in node.children if isinstance(child, Tag)
        )
        return f"<{node.name}[{attr_repr}]{children}>"

    def _diff_children(self, a: Tag, b: Tag, path: list[str], out: list[str]) -> None:
        a_children = [c for c in a.children if isinstance(c, Tag)]
        b_children = [c for c in b.children if isinstance(c, Tag)]
        if len(a_children) != len(b_children):
            return
        for ca, cb in zip(a_children, b_children, strict=False):
            self._diff_walk(ca, cb, [*path, a.name or "?"], out)

    def _diff_walk(
        self,
        a: BeautifulSoup | Tag,
        b: BeautifulSoup | Tag,
        path: list[str],
        out: list[str],
    ) -> None:
        if not isinstance(a, Tag) or not isinstance(b, Tag):
            return
        if self._tree_repr(a) == self._tree_repr(b):
            return
        region = " > ".join([*path, a.name or "?"])
        if region not in out:
            out.append(region)
        self._diff_children(a, b, path, out)

__all__ = ["PageSignature"]
