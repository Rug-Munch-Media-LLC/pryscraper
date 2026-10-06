"""Sitemap-driven discovery tier — flatten sitemaps and locate them via robots.txt."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from urllib.parse import urlparse

from defusedxml import ElementTree as ET  # noqa: N817

from pry.engine.methods import _common
from pry.engine.methods._common import _localname, _resolve_candidate

logger = logging.getLogger(__name__)

_MAX_SITEMAP_DEPTH = 2
_MAX_SITEMAP_FETCHES = 20


def _walk_sitemap(url: str, out: list[str], seen: set[str], *, depth: int) -> None:
    """Fetch a sitemap, flattening sitemap indexes into the ``out`` list.

    Bounded by :data:`_MAX_SITEMAP_DEPTH` and :data:`_MAX_SITEMAP_FETCHES`;
    ``seen`` prevents re-fetching the same sitemap URL (cycle safety).
    """
    if depth > _MAX_SITEMAP_DEPTH or len(seen) >= _MAX_SITEMAP_FETCHES:
        return
    if url in seen:
        return
    seen.add(url)
    response = _common._sync_get(url)
    if response is None:
        return
    try:
        # Sitemap XML is untrusted; parsing is best-effort and bounded.
        # (defusedxml used for safe XML parsing of untrusted input.)
        root = ET.fromstring(response.text)
    except (ET.ParseError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return
    locs = [
        child.text.strip()
        for child in root.iter()
        if _localname(child.tag) == "loc" and child.text and child.text.strip()
    ]
    if _localname(root.tag) == "sitemapindex":
        for nested in locs[: _MAX_SITEMAP_FETCHES - len(seen)]:
            _walk_sitemap(nested, out, seen, depth=depth + 1)
        return
    for loc in locs:
        if loc not in out:
            out.append(loc)


def parse_sitemap(url: str) -> list[str]:
    """Fetch and parse a sitemap (``urlset``) or sitemap index.

    A ``<sitemapindex>`` is flattened by recursively fetching each referenced
    sub-sitemap (bounded recursion, cycle-safe); a ``<urlset>`` contributes
    its ``<url><loc>`` entries directly.

    Args:
        url: Absolute http(s) URL of the sitemap or sitemap index.

    Returns:
        De-duplicated list of URLs found in the sitemap, or ``[]`` on any
        failure. Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    urls: list[str] = []
    _walk_sitemap(url, urls, set(), depth=0)
    return urls


def discover_sitemap(domain: str) -> str | None:
    """Locate a sitemap URL for a domain via ``robots.txt``.

    Fetches ``<origin>/robots.txt`` and returns the first ``Sitemap:`` line.
    When robots.txt is unreachable or has no ``Sitemap:`` line, falls back to
    the conventional ``<origin>/sitemap.xml`` URL.

    Args:
        domain: A bare domain (``example.com``) or a full http(s) URL; a bare
            domain is normalized to ``https://``.

    Returns:
        The absolute sitemap URL, or None for unusable input. Never raises.
    """
    if not isinstance(domain, str) or not domain.strip():
        return None
    domain = domain.strip()
    if "://" not in domain:
        domain = f"https://{domain}"
    try:
        parsed = urlparse(domain)
    except ValueError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{base}/robots.txt"
    response = _common._sync_get(robots_url)
    if response is not None:
        for line in response.text.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("sitemap:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            if value:
                resolved = _resolve_candidate(value, robots_url)
                if resolved is not None:
                    return resolved
    fallback = f"{base}/sitemap.xml"
    return fallback if _resolve_candidate(fallback, base) is not None else None


__all__ = ["discover_sitemap", "parse_sitemap"]
