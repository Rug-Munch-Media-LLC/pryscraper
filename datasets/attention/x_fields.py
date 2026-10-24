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

MAX_WALK_DEPTH = 3
MAX_WALK_NODES = 300
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


def nearest_user(node: dict[str, Any]) -> dict[str, Any]:
    """Breadth-first search for the nearest ``user_results.result`` node."""
    queue: list[tuple[Any, int]] = [(node, 0)]
    visited = 0
    while queue and visited < MAX_WALK_NODES:
        current, depth = queue.pop(0)
        visited += 1
        if isinstance(current, dict):
            users = current.get("user_results")
            if isinstance(users, dict) and isinstance(users.get("result"), dict):
                return users["result"]
            if depth < MAX_WALK_DEPTH:
                queue.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list) and depth < MAX_WALK_DEPTH:
            queue.extend((child, depth + 1) for child in current)
    return {}


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


def _entities(result: dict[str, Any], key: str, field: str) -> list[str]:
    """Collect a text field from modern ``details`` or legacy ``entities``."""
    details = result.get("details") or {}
    modern = details.get(f"{key}_entities") or []
    legacy = ((result.get("legacy") or {}).get("entities") or {}).get(key) or []
    out: list[str] = []
    for item in list(modern) + list(legacy):
        value = item.get(field) if isinstance(item, dict) else None
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out


def _media(result: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize attached media to ``{type, url}`` pairs."""
    out: list[dict[str, str]] = []
    modern = result.get("media_entities2") or []
    legacy = ((result.get("legacy") or {}).get("extended_entities") or {}).get("media") or []
    urls: set[str] = set()
    for item in list(modern) + list(legacy):
        if not isinstance(item, dict):
            continue
        url = _first_str(
            item.get("media_url_https"),
            item.get("url"),
            (item.get("media_info") or {}).get("original_img_url"),
        )
        if url and url not in urls:
            urls.add(url)
            out.append({"type": str(item.get("type") or ""), "url": url})
    return out


def post_from_result(result: Any) -> dict[str, Any] | None:
    """Normalize one ``tweet_results.result`` node; None when unusable."""
    if not isinstance(result, dict):
        return None
    # ``tweet_results`` nodes wrap the tweet in ``result``; retweets wrap it again.
    if isinstance(result.get("result"), dict):
        result = result["result"]
    if "legacy" not in result and "details" not in result and isinstance(result.get("tweet"), dict):
        result = result["tweet"]
    tweet_id = str(result.get("rest_id") or "")
    if not tweet_id:
        return None
    details = result.get("details") or {}
    legacy = result.get("legacy") or {}
    counts = result.get("counts") or {}
    author = _author(result)
    reply_to = _first_str(legacy.get("in_reply_to_status_id_str"))
    handle = author["handle"]
    path = f"/{handle}" if handle else "/i"
    return {
        "id": tweet_id,
        "url": f"https://x.com{path}/status/{tweet_id}",
        "text": html_unescape(_first_str(details.get("full_text"), legacy.get("full_text"))),
        "created_at": iso_from_ms(details.get("created_at_ms"))
        or iso_from_legacy(legacy.get("created_at")),
        "lang": _first_str(legacy.get("lang")) or None,
        "author": author,
        "metrics": {
            "likes": _as_int(counts.get("favorite_count") or legacy.get("favorite_count")),
            "reposts": _as_int(counts.get("retweet_count") or legacy.get("retweet_count")),
            "replies": _as_int(counts.get("reply_count") or legacy.get("reply_count")),
            "quotes": _as_int(counts.get("quote_count") or legacy.get("quote_count")),
            "bookmarks": _as_int(counts.get("bookmark_count") or legacy.get("bookmark_count")),
            "views": _as_int((result.get("views") or {}).get("count")),
        },
        "hashtags": _entities(result, "hashtag", "text"),
        "urls": _entities(result, "url", "expanded_url") or _entities(result, "url", "url"),
        "media": _media(result),
        "is_reply": bool(reply_to),
        "in_reply_to_id": reply_to or None,
    }
