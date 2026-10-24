"""Pry — X (Twitter) DOM fallback parser.

When a page carries no SSR JSON (A/B variants, stripped payloads), the
rendered ``article[data-testid="tweet"]`` blocks still hold the status id,
author handle, text and timestamp. This module extracts exactly those four
fields — it never invents counts, media, or engagement numbers it cannot
read.

Contract:
    >>> parse_dom(html)[0]["id"]
    '20'

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import Any

_ARTICLE_RE = re.compile(r'<article[^>]*data-testid="tweet".*?</article>', re.S)
_TEXT_RE = re.compile(r'data-testid="tweetText"[^>]*>(.+?)</div>', re.S)
_NAME_RE = re.compile(r'href="/([A-Za-z0-9_]{1,15})"')
_STATUS_RE = re.compile(r'href="[^"]*?/([A-Za-z0-9_]{1,15})/status/(\d{1,25})"')
_DATETIME_RE = re.compile(r'datetime="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")

_USER_NAME_MARK = 'data-testid="User-Name"'
_NAME_WINDOW = 2000

__all__ = ["parse_dom"]


def _clean(fragment: str) -> str:
    """Strip tags and collapse whitespace in a DOM fragment."""
    return " ".join(html_unescape(_TAG_RE.sub(" ", fragment)).split())


def _empty_metrics() -> dict[str, int]:
    """Zeroed metric block (DOM carries no reliable counts)."""
    return {"likes": 0, "reposts": 0, "replies": 0, "quotes": 0, "bookmarks": 0, "views": 0}


def _dom_post(block: str, handle: str, tweet_id: str) -> dict[str, Any]:
    """Build one normalized post from an ``article`` block."""
    text_match = _TEXT_RE.search(block)
    name_at = block.find(_USER_NAME_MARK)
    name_match = _NAME_RE.search(block[name_at : name_at + _NAME_WINDOW]) if name_at >= 0 else None
    when = _DATETIME_RE.search(block)
    return {
        "id": tweet_id,
        "url": f"https://x.com/{handle}/status/{tweet_id}",
        "text": _clean(text_match.group(1)) if text_match else "",
        "created_at": when.group(1) if when else None,
        "lang": None,
        "author": {
            "id": "",
            "handle": name_match.group(1) if name_match else handle,
            "name": "",
            "followers": 0,
            "verified": False,
        },
        "metrics": _empty_metrics(),
        "hashtags": [],
        "urls": [],
        "media": [],
        "is_reply": False,
        "in_reply_to_id": None,
    }


def parse_dom(html: str) -> list[dict[str, Any]]:
    """Parse ``article[data-testid="tweet"]`` blocks (no-SSR fallback)."""
    posts: list[dict[str, Any]] = []
    for block in _ARTICLE_RE.findall(html):
        status = _STATUS_RE.search(block)
        if status is None:
            continue
        posts.append(_dom_post(block, status.group(1), status.group(2)))
    return posts
