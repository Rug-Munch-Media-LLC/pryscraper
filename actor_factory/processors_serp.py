"""Pry - Apify Actor Factory: SERP result processor.

Turns a scraped search-engine results page into ranked, structured
organic/paid results. Used by the SERP scraper and rank-tracker actors,
whose READMEs promise ranked result rows rather than raw page content.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from actor_factory.processors_common import _base_item, _raw_html

_SKIP_HOSTS = ("google.", "bing.", "duckduckgo.", "search.yahoo.", "yandex.", "baidu.")
_AD_MARKERS = ("/aclk?", "adurl=", "&ad=", "/ads/", "sponsored")


def _is_ad(href: str, html_around: str) -> bool:
    lowered = href.lower()
    if any(marker in lowered for marker in _AD_MARKERS):
        return True
    return "sponsored" in html_around.lower() or "ad badge" in html_around.lower()


def _parse_limit(options: dict[str, Any]) -> int:
    raw = options.get("num_results", options.get("depth", 10))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 10


def _collect_rows(html: str, include_ads: bool, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = r"""<a\s[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a>"""
    for match in re.finditer(pattern, html, re.I | re.S):
        href, inner = match.group(1), match.group(2)
        host = urlparse(href).netloc.lower()
        if not host or any(host.startswith(h) for h in _SKIP_HOSTS) or host in seen:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if len(title) < 3:
            continue
        is_ad = _is_ad(href, match.group(0))
        if is_ad and not include_ads:
            continue
        seen.add(host)
        rows.append(
            {
                "rank": len(rows) + 1,
                "title": title[:200],
                "url": href,
                "domain": host,
                "is_ad": is_ad,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def process_serp(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Emit ranked SERP rows: rank, title, url, domain, is_ad."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    html = _raw_html(result) or item["content"] or ""
    rows = _collect_rows(
        html, bool(options.get("include_ads", True)), _parse_limit(options)
    )
    if not rows:
        item["status"] = "skipped"
        item["error"] = "no organic results found in page"
    item.pop("content", None)
    item["serp"] = {"query_url": url, "results": rows, "count": len(rows)}
    return item
