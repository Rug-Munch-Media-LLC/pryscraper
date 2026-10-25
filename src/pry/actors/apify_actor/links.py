"""Same-domain link extraction for the actor's crawl mode."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

MAX_LINKS_PER_PAGE = 50


def _extract_links(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from raw HTML for crawling.

    Handles absolute URLs AND root-relative hrefs (``/path``) - the latter
    are the majority on real sites and were previously dropped entirely,
    crippling crawl mode (the old relative branch was unreachable because
    the only regex matched absolute URLs).
    """
    links: list[str] = []
    parsed_base = urlparse(base_url)
    domain = parsed_base.netloc

    hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    hrefs += re.findall(r'href=["\'](/[^"\']*)["\']', html, re.IGNORECASE)

    for href in hrefs:
        link = urljoin(base_url, href)
        link_parsed = urlparse(link)
        if link_parsed.netloc == domain and link_parsed.scheme in ("http", "https"):
            clean = link.split("#")[0]
            if clean not in links:
                links.append(clean)

    return links[:MAX_LINKS_PER_PAGE]  # cap per page
