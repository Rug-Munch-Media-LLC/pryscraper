"""Yelp review extraction (embedded JSON primary, HTML cards fallback).

The business page (``yelp.com/biz/{slug}``) embeds reviews in the
``data-hydrated-app-id="yelp-biz-page"`` JSON script (stable) with an HTML
review-card fallback. Pagination follows Yelp's ``start`` parameter
(``sort_by=date_desc``), capped by ``PRY_LOCAL_YELP_MAX_PAGES`` so we
never hammer the site.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from lxml import html as lxml_html

from datasets.local_data.reviews_common import (
    _DATE_RE,
    _clean_text,
    _env_int,
    _http_get,
    _is_anti_bot,
    _iter_dicts,
    _normalize_date,
    _opt_float,
    _robots_allowed,
)

logger = logging.getLogger(__name__)

YELP_MAX_PAGES = 5  # pagination cap for the "full history" sweep
YELP_BIZ_URL = "https://www.yelp.com/biz/{slug}"

_YELP_BIZ_JSON_RE = re.compile(
    r'<script[^>]*data-hydrated-app-id=["\']yelp-biz-page["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


# ── URL building ─────────────────────────────────────────────────────────
def _yelp_url(slug: str, start: int = 0) -> str:
    """Build a Yelp business-page URL with date-sorted pagination."""
    base = YELP_BIZ_URL.format(slug=quote(slug))
    query = "sort_by=date_desc"
    if start:
        query += f"&start={start}"
    return f"{base}?{query}"


# ── Yelp: embedded JSON (primary) ────────────────────────────────────────
def _yelp_review_from_json(item: Any) -> dict[str, Any] | None:
    """Normalize a Yelp ``yelp-biz-page`` review object into a record."""
    if not isinstance(item, dict):
        return None
    text = _clean_text(item.get("text"))
    rating = _opt_float(item.get("rating"))
    if not text or rating is None:
        return None
    user = item.get("user")
    author = _clean_text(user.get("name")) if isinstance(user, dict) else ""
    date = _normalize_date(_clean_text(item.get("time_created")))
    return {
        "author": author,
        "rating": float(rating),
        "text": text,
        "date": date,
        "source": "yelp",
    }


def _yelp_reviews_from_json(html_text: str) -> list[dict[str, Any]]:
    """Parse the ``data-hydrated-app-id="yelp-biz-page"`` JSON payload."""
    match = _YELP_BIZ_JSON_RE.search(html_text)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for d in _iter_dicts(data):
        for key in ("reviews", "reviewFeed"):
            items = d.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                rec = _yelp_review_from_json(item)
                if not rec:
                    continue
                dedupe_key = (rec["author"].lower(), rec["text"][:60].lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                out.append(rec)
    return out


# ── Yelp: HTML review cards (fallback) ───────────────────────────────────
def _parse_star_title(value: str) -> float | None:
    """Parse "5.0 star rating" from an i-stars title/aria-label."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*star", value, re.IGNORECASE)
    return _opt_float(m.group(1)) if m else None


def _node_join(node: Any, xpath: str) -> str:
    """Join all text/attr matches for ``xpath`` under ``node`` into a string."""
    return _clean_text(" ".join(node.xpath(xpath)))


def _parse_aria_review(label: str) -> tuple[str, str]:
    """Parse "review by Alice J. on 2/15/2024" → (author, date)."""
    m = re.search(r"review by\s+(.+?)(?:\s+on\s+(.+?))?$", label, re.IGNORECASE)
    if not m:
        return "", ""
    return m.group(1).strip(), (m.group(2).strip() if m.group(2) else "")


def _review_cards(tree: Any) -> list[Any]:
    """Collect Yelp review-card nodes (new aria-label layout + legacy classes)."""
    cards: list[Any] = []
    seen: set[int] = set()
    xpaths = (
        "//*[@role='region' and contains(@aria-label, 'review')]",
        "//li[contains(@aria-label, 'review')]",
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' review ') "
        "and not(contains(concat(' ', normalize-space(@class), ' '), ' review-content '))]",
    )
    for xp in xpaths:
        for node in tree.xpath(xp):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            cards.append(node)
    return cards


def _yelp_reviews_from_html(html_text: str) -> list[dict[str, Any]]:
    """Parse Yelp review cards from raw HTML (legacy page fallback)."""
    try:
        tree = lxml_html.fromstring(html_text)
    except (ValueError, TypeError):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in _review_cards(tree):
        aria_author, aria_date = _parse_aria_review(_node_join(node, "@aria-label"))
        author = _node_join(node, ".//*[contains(@class, 'user-display-name')]//text()")
        if not author:
            author = aria_author
        rating = _parse_star_title(_node_join(node, ".//*[contains(@class, 'i-stars')]/@title"))
        text = _node_join(node, ".//p[@lang]//text()")
        if not text:
            text = _node_join(node, ".//*[contains(@class, 'review-content')]//text()")
        date = _node_join(node, ".//meta[@itemprop='datePublished']/@content")
        if not date:
            date = aria_date
        if not date:
            for chunk in node.xpath(".//text()"):
                m = _DATE_RE.search(chunk)
                if m:
                    date = m.group(0)
                    break
        if not author or rating is None or not text:
            continue
        key = (author.lower(), text[:60].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "author": author,
                "rating": rating,
                "text": text,
                "date": date,
                "source": "yelp",
            }
        )
    return out


def _parse_yelp_reviews(html_text: str) -> list[dict[str, Any]]:
    """Yelp reviews: embedded JSON first, HTML cards as fallback."""
    records = _yelp_reviews_from_json(html_text)
    if records:
        return records
    return _yelp_reviews_from_html(html_text)


# ── Fetcher ──────────────────────────────────────────────────────────────
async def _reviews_yelp(slug: str, limit: int) -> list[dict[str, Any]]:
    """Fetch + parse Yelp reviews, paginating by ``start`` until limit/cap."""
    if not await _robots_allowed(_yelp_url(slug, 0)):
        return []
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    max_pages = _env_int("PRY_LOCAL_YELP_MAX_PAGES", YELP_MAX_PAGES)
    for page in range(max_pages):
        url = _yelp_url(slug, page * 10)
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            break
        html_text = resp.text
        if _is_anti_bot(html_text):
            logger.warning("yelp_anti_bot", extra={"slug": slug})
            break
        fresh = 0
        for rec in _parse_yelp_reviews(html_text):
            key = (rec["author"].strip().lower(), rec["text"][:60].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            collected.append(rec)
            fresh += 1
        if fresh == 0 or len(collected) >= limit:
            break
    return collected
