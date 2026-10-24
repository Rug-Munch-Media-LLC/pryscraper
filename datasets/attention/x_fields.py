"""Pry — X (Twitter) post field normalization.

Turns one ``tweet_results.result`` node into Pry's normalized post shape.
Modern X serves the interesting fields under ``result.details``,
``result.counts`` and ``result.core.user_results``; older payloads still
use ``result.legacy``. Both are read, modern first.

The author comes from the tweet's own ``core.user_results``; when that is
absent (retweets, promoted entries) the nearest ``user_results`` in the
enclosing node is used instead.

Contract:
    >>> post = post_from_result(node)
    >>> post["author"]["handle"], post["metrics"]["likes"]
    ('jack', 309039)

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datetime import UTC, datetime
from html import unescape as html_unescape
from typing import Any

from datasets.attention.x_walk import nearest_user

_LEGACY_TIME = "%a %b %d %H:%M:%S %z %Y"

__all__ = ["iso_from_legacy", "iso_from_ms", "nearest_user", "post_from_result"]

def _as_int(value: Any) -> int:
    """Coerce a count field to int (0 for anything unusable)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0

def iso_from_ms(value: Any) -> str | None:
    """Epoch milliseconds -> ISO-8601 UTC (None when unusable)."""
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, OverflowError, ValueError):
        return None

def iso_from_legacy(value: Any) -> str | None:
    """Legacy ``Wed Nov 23 12:34:56 +0000 2016`` -> ISO-8601 UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.strptime(value, _LEGACY_TIME)
    except ValueError:
        return None
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def _first_str(*values: Any) -> str:
    """Return the first non-empty string among ``values``."""
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""

def _author(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize the tweet author (modern ``core`` first, legacy second)."""
    users = result.get("core") or {}
    user = (users.get("user_results") or {}).get("result") if isinstance(users, dict) else None
    if not isinstance(user, dict):
        user = nearest_user(result)
    core = user.get("core") or {}
    legacy = user.get("legacy") or {}
    handle = _first_str(core.get("screen_name"), legacy.get("screen_name"))
    return {
        "id": str(user.get("rest_id") or ""),
        "handle": handle,
        "name": _first_str(core.get("name"), legacy.get("name")),
        "followers": _as_int((user.get("relationship_counts") or {}).get("followers")),
        "verified": bool((user.get("verification") or {}).get("is_blue_verified")),
    }

def _unique_values(items: list[Any], field: str) -> list[str]:
    """Collect unique non-empty string ``field`` values from dict items."""
    out: list[str] = []
    for item in items:
        value = item.get(field) if isinstance(item, dict) else None
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out

def _entities(result: dict[str, Any], key: str, field: str) -> list[str]:
    """Collect a text field from modern ``details`` or legacy ``entities``."""
    details = result.get("details") or {}
    modern = details.get(f"{key}_entities") or []
    legacy = ((result.get("legacy") or {}).get("entities") or {}).get(key) or []
    return _unique_values(list(modern) + list(legacy), field)

def _media_url(item: Any) -> str:
    """Best URL for one media item (empty when unusable)."""
    if not isinstance(item, dict):
        return ""
    return _first_str(
        item.get("media_url_https"),
        item.get("url"),
        (item.get("media_info") or {}).get("original_img_url"),
    )

def _media(result: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize attached media to ``{type, url}`` pairs."""
    modern = result.get("media_entities2") or []
    legacy = ((result.get("legacy") or {}).get("extended_entities") or {}).get("media") or []
    out: list[dict[str, str]] = []
    urls: set[str] = set()
    for item in list(modern) + list(legacy):
        url = _media_url(item)
        if url and url not in urls:
            urls.add(url)
            out.append({"type": str(item.get("type") or ""), "url": url})
    return out

def _unwrap(result: Any) -> dict[str, Any] | None:
    """Peel ``result``/``tweet`` wrappers; None when the node is not a tweet."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("result"), dict):
        result = result["result"]
    if "legacy" not in result and "details" not in result and isinstance(result.get("tweet"), dict):
        result = result["tweet"]
    return result

def _metrics(result: dict[str, Any]) -> dict[str, int]:
    """Normalize engagement counts from modern ``counts`` or legacy fields."""
    counts = result.get("counts") or {}
    legacy = result.get("legacy") or {}
    return {
        "likes": _as_int(counts.get("favorite_count") or legacy.get("favorite_count")),
        "reposts": _as_int(counts.get("retweet_count") or legacy.get("retweet_count")),
        "replies": _as_int(counts.get("reply_count") or legacy.get("reply_count")),
        "quotes": _as_int(counts.get("quote_count") or legacy.get("quote_count")),
        "bookmarks": _as_int(counts.get("bookmark_count") or legacy.get("bookmark_count")),
        "views": _as_int((result.get("views") or {}).get("count")),
    }

def _created_at(details: dict[str, Any], legacy: dict[str, Any]) -> str | None:
    """ISO timestamp from modern milliseconds or the legacy string."""
    return iso_from_ms(details.get("created_at_ms")) or iso_from_legacy(legacy.get("created_at"))

def _urls(result: dict[str, Any]) -> list[str]:
    """Expanded URLs first, then raw t.co URLs."""
    return _entities(result, "url", "expanded_url") or _entities(result, "url", "url")

def post_from_result(result: Any) -> dict[str, Any] | None:
    """Normalize one ``tweet_results.result`` node; None when unusable."""
    result = _unwrap(result)
    if result is None:
        return None
    tweet_id = str(result.get("rest_id") or "")
    if not tweet_id:
        return None
    details = result.get("details") or {}
    legacy = result.get("legacy") or {}
    author = _author(result)
    reply_to = _first_str(legacy.get("in_reply_to_status_id_str"))
    handle = author["handle"]
    path = f"/{handle}" if handle else "/i"
    return {
        "id": tweet_id,
        "url": f"https://x.com{path}/status/{tweet_id}",
        "text": html_unescape(_first_str(details.get("full_text"), legacy.get("full_text"))),
        "created_at": _created_at(details, legacy),
        "lang": _first_str(legacy.get("lang")) or None,
        "author": author,
        "metrics": _metrics(result),
        "hashtags": _entities(result, "hashtag", "text"),
        "urls": _urls(result),
        "media": _media(result),
        "is_reply": bool(reply_to),
        "in_reply_to_id": reply_to or None,
    }
