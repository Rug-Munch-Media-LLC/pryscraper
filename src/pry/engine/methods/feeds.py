"""RSS/Atom feed parsing tier — parse feeds and discover feed links from pages."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defusedxml import ElementTree as ET  # noqa: N817

from pry.engine.methods import _common
from pry.engine.methods._common import _localname, _resolve_candidate

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element as _ETElement
import logging

logger = logging.getLogger(__name__)

_FEED_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_FEED_REL_ALTERNATE_RE = re.compile(r"""rel\s*=\s*["']alternate["']""", re.IGNORECASE)
_FEED_TYPE_RE = re.compile(r"""type\s*=\s*["']application/(?:rss|atom)\+xml["']""", re.IGNORECASE)
_FEED_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _rss_entries(root: _ETElement) -> list[dict[str, str]]:
    """Extract RSS 2.0 ``<item>`` entries as flat dicts."""
    channel = next((child for child in root if _localname(child.tag) == "channel"), None)
    if channel is None:
        return []
    entries: list[dict[str, str]] = []
    for item in channel:
        if _localname(item.tag) != "item":
            continue
        entry = {"title": "", "link": "", "summary": "", "published": ""}
        for field in item:
            name = _localname(field.tag)
            text = (field.text or "").strip()
            if name == "title":
                entry["title"] = text
            elif name == "link":
                entry["link"] = text
            elif name == "description":
                entry["summary"] = text
            elif name == "pubDate":
                entry["published"] = text
        entries.append(entry)
    return entries


def _atom_entries(root: _ETElement) -> list[dict[str, str]]:
    """Extract Atom ``<entry>`` elements as flat dicts."""
    entries: list[dict[str, str]] = []
    for child in root:
        if _localname(child.tag) != "entry":
            continue
        entry = {"title": "", "link": "", "summary": "", "published": ""}
        for field in child:
            name = _localname(field.tag)
            if name == "title":
                entry["title"] = (field.text or "").strip()
            elif name == "link":
                href = field.attrib.get("href")
                if href:
                    entry["link"] = href.strip()
            elif name in ("summary", "content") and not entry["summary"]:
                entry["summary"] = (field.text or "").strip()
            elif name in ("published", "updated") and not entry["published"]:
                entry["published"] = (field.text or "").strip()
        entries.append(entry)
    return entries


def parse_feed(url: str) -> list[dict[str, str]]:
    """Fetch and parse an RSS 2.0 or Atom feed into structured entries.

    Args:
        url: Absolute http(s) URL of the feed.

    Returns:
        A list of entries, each with the keys ``title``, ``link``,
        ``summary`` and ``published`` (empty string when a field is absent).
        Atom ``<content>`` / ``<updated>`` fall back to ``summary`` /
        ``published`` when ``<summary>`` / ``<published>`` are missing.
        Never raises: returns ``[]`` for unusable input, fetch or parse
        failures.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    response = _common._sync_get(url)
    if response is None:
        return []
    try:
        # Feed XML is untrusted; parsing is best-effort and failures return [].
        # (defusedxml used for safe XML parsing of untrusted input.)
        root = ET.fromstring(response.text)
    except (ET.ParseError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return []
    root_name = _localname(root.tag)
    if root_name == "rss":
        return _rss_entries(root)
    if root_name == "feed":
        return _atom_entries(root)
    return []


def discover_feed(page_url: str, html: str) -> str | None:
    """Find the RSS/Atom feed URL advertised by a page.

    Scans for ``<link rel="alternate" type="application/rss+xml|atom+xml">``
    (attribute order-insensitive) and resolves the ``href`` against
    ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from.
        html: Raw page HTML.

    Returns:
        The absolute feed URL, or None when no alternate feed link is found.
        Never raises.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return None
    page_url = page_url.strip()
    if not page_url or not html:
        return None
    for tag in _FEED_TAG_RE.findall(html):
        if not _FEED_REL_ALTERNATE_RE.search(tag) or not _FEED_TYPE_RE.search(tag):
            continue
        match = _FEED_HREF_RE.search(tag)
        if match is None:
            continue
        resolved = _resolve_candidate(match.group(1), page_url)
        if resolved is not None:
            return resolved
    return None


__all__ = ["discover_feed", "parse_feed"]
