"""DOM context capture and selector synthesis for adaptive selectors.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def attrs_of(node: Tag) -> dict[str, str]:
    """Flatten a tag's attributes to str -> str (bs4 may give lists)."""
    out: dict[str, str] = {}
    for key, value in node.attrs.items():
        if isinstance(value, (list, tuple)):
            out[key] = " ".join(str(v) for v in value)
        else:
            out[key] = str(value)
    return out


def attr_similarity(a: dict[str, str], b: dict[str, str]) -> float:
    """Jaccard-ish similarity over attribute key=value pairs."""
    if not a and not b:
        return 0.5  # no attributes on either side: neutral signal
    keys = set(a) | set(b)
    if not keys:
        return 0.5
    hits = sum(1 for k in keys if a.get(k) == b.get(k) and a.get(k) is not None)
    return hits / len(keys)


def structural_path(node: Tag) -> list[str]:
    """Tag names from root down to (and including) this node."""
    names: list[str] = []
    current: Tag | None = node
    while current is not None and current.name:
        names.append(current.name)
        current = current.parent if isinstance(current.parent, Tag) else None
    names.reverse()
    return names


def path_similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class ElementContext:
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
    def from_dict(cls, data: dict[str, Any]) -> ElementContext:
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


def capture_context(node: Tag, selector: str) -> ElementContext:
    """Snapshot the surroundings of a matched element."""
    parent = node.parent if isinstance(node.parent, Tag) else None
    siblings = [s for s in node.find_previous_siblings() if isinstance(s, Tag)]
    prev = siblings[0] if siblings else None
    return ElementContext(
        selector=selector,
        tag=node.name or "",
        attrs=attrs_of(node),
        text=norm_text(node.get_text(" ", strip=True))[:500],
        parent_tag=parent.name if parent else "",
        parent_attrs=attrs_of(parent) if parent else {},
        sibling_tags=[s.name or "" for s in siblings[:5]],
        sibling_text=norm_text(prev.get_text(" ", strip=True))[:200] if prev else "",
        path=structural_path(node),
    )


def _id_selector(node: Tag) -> str | None:
    return f"{node.name}#{node['id']}" if node.get("id") else None


def _class_selector(node: Tag) -> str | None:
    classes = node.get("class")
    if isinstance(classes, (list, tuple)) and classes:
        return f"{node.name}." + ".".join(str(c) for c in classes[:2])
    return None


def _attr_selector(node: Tag, attrs: dict) -> str | None:
    if "data-testid" in attrs:
        return f'{node.name}[data-testid="{attrs["data-testid"]}"]'
    if "name" in attrs:
        return f'{node.name}[name="{attrs["name"]}"]'
    return None


def _nth_of_type(node: Tag) -> str:
    parent = node.parent if isinstance(node.parent, Tag) else None
    if parent is None:
        return node.name or "*"
    same_tag = [c for c in parent.children if isinstance(c, Tag) and c.name == node.name]
    index = same_tag.index(node) + 1 if node in same_tag else 1
    parent_sel = (
        synthesize_selector(parent)
        if parent.name not in ("[document]", "html")
        else parent.name
    )
    return f"{parent_sel} > {node.name}:nth-of-type({index})"


def synthesize_selector(node: Tag) -> str:
    """Build a reasonably specific CSS selector for a node."""
    attrs = attrs_of(node)
    for candidate in (
        _id_selector(node),
        _class_selector(node),
        _attr_selector(node, attrs),
    ):
        if candidate:
            return candidate
    return _nth_of_type(node)

__all__ = [
    "ElementContext",
    "attr_similarity",
    "attrs_of",
    "capture_context",
    "norm_text",
    "path_similarity",
    "soup_of",
    "structural_path",
    "synthesize_selector",
]
