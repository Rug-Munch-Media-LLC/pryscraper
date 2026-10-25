"""Pry — Google result-URL cleaning and SERP query-URL assembly."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse

from .config import _MAX_NUM, _SERP_URL


def _clean_google_url(href: str) -> str:
    """Resolve a Google result href to the real destination URL.

    Modern SERPs wrap organic links as ``/url?q=<target>&sa=U&...``;
    older layouts link directly. Returns ``""`` when the href is not a
    usable organic result link.
    """
    if not href:
        return ""
    if href.startswith("/url?"):
        q = parse_qs(urlparse(href).query).get("q")
        if not q:
            return ""
        target = q[0]
        if "google." in urlparse(target).netloc:
            return ""
        return target
    if href.startswith(("http://", "https://")):
        netloc = urlparse(href).netloc
        if "google." not in netloc:
            return href
    return ""


def _serp_url(query: str, num: int) -> str:
    """Absolute Google SERP URL for a query (shared by the fetch tiers)."""
    params = {
        "q": query,
        "num": str(min(max(num, 1), _MAX_NUM)),
        "hl": "en",
        "gl": "us",
    }
    return f"{_SERP_URL}?{urlencode(params)}"
