"""Pry — organic-result extraction from a parsed SERP document."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from .text import _extract_snippet, _text
from .urls import _clean_google_url


def _extract_results(root: Any, num: int) -> list[dict[str, Any]]:
    """Extract organic results from the parsed SERP document.

    Strategy A targets the current ``div.MjjYud`` / ``div.g`` wrappers;
    strategy B anchors on every ``<h3>`` and walks up to its wrapping
    anchor (current obfuscated DOM). A empty strategy A falls through to B.
    """
    cap = max(num, 1)
    results = _block_results(root, cap)
    if not results:
        results = _heading_results(root, cap)
    return results


def _block_results(root: Any, cap: int) -> list[dict[str, Any]]:
    """Strategy A: ``div.MjjYud`` / ``div.g`` wrapper blocks."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        blocks = root.cssselect(".MjjYud") or root.cssselect("div.g")
    except (AttributeError, TypeError, ValueError):
        return results
    for block in blocks:
        entry = _block_entry(block, seen)
        if entry is None:
            continue
        seen.add(entry["url"])
        results.append({**entry, "position": len(results) + 1})
        if len(results) >= cap:
            break
    return results


def _block_entry(block: Any, seen: set[str]) -> dict[str, str] | None:
    """One wrapper block -> ``{title, url, snippet}``, or None to skip it."""
    anchor: Any | None = None
    try:
        for a in block.cssselect("a[href]"):
            if a.cssselect("h3"):
                anchor = a
                break
    except (AttributeError, TypeError, ValueError):
        return None
    if anchor is None:
        return None
    url = _clean_google_url(anchor.get("href", ""))
    if not url or url in seen:
        return None
    try:
        title = _text(anchor.cssselect("h3")[0])
    except (AttributeError, TypeError, ValueError, IndexError):
        title = ""
    if not title:
        return None
    return {"title": title, "url": url, "snippet": _extract_snippet(block)}


def _heading_results(root: Any, cap: int) -> list[dict[str, Any]]:
    """Strategy B: anchor on every ``<h3>``, resolve its ancestor ``<a>``.

    Current Google DOM container classes are obfuscated and organic links are
    wrapped in an opaque ``/goto?url=<token>`` redirect; the redirect is
    resolved later in ``serp()``.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        headings = root.cssselect("h3")
    except (AttributeError, TypeError, ValueError):
        headings = []
    for heading in headings:
        link = _link_ancestor(heading)
        if link is None:
            continue
        url = _clean_google_url(link.get("href", ""))
        if not url:
            href = link.get("href", "")
            if href.startswith("/"):
                url = "https://www.google.com" + href
        if not url or url in seen:
            continue
        title = _text(heading)
        if not title:
            continue
        seen.add(url)
        container = link.getparent()
        results.append(
            {
                "position": len(results) + 1,
                "title": title,
                "url": url,
                "snippet": _extract_snippet(container) if container is not None else "",
            }
        )
        if len(results) >= cap:
            break
    return results


def _link_ancestor(heading: Any) -> Any | None:
    """Nearest ancestor of ``heading`` that is an ``<a href>`` (max 4 levels)."""
    node = heading
    for _ in range(4):
        node = node.getparent()
        if node is None:
            return None
        if node.tag == "a" and node.get("href"):
            return node
    return None
