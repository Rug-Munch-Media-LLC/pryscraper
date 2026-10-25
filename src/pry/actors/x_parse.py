"""Normalize X syndication payloads into plain tweet dicts. No network here.

The syndication timeline ships a Next.js page whose ``__NEXT_DATA__`` JSON
island holds nested tweet objects; their depth has changed across X releases,
so extraction walks the tree instead of hard-coding a path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
MAX_DEPTH = 40


def _walk(node: Any, depth: int = 0) -> Iterator[dict]:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, dict):
        if ("full_text" in node or "text" in node) and ("id_str" in node or "rest_id" in node):
            yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, depth + 1)


def _handle(tweet: dict) -> str:
    user = tweet.get("user") or tweet.get("core", {}).get("user_results", {}).get("result", {})
    if isinstance(user, dict):
        if user.get("screen_name"):
            return str(user["screen_name"])
        legacy = user.get("legacy")
        if isinstance(legacy, dict) and legacy.get("screen_name"):
            return str(legacy["screen_name"])
    return ""


def _author_name(tweet: dict) -> str:
    user = tweet.get("user")
    if isinstance(user, dict):
        return str(user.get("name") or "")
    return ""


def _count(tweet: dict, *keys: str) -> int:
    for key in keys:
        value = tweet.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def normalize_tweets(html: str, handle: str, limit: int = 20) -> list[dict]:
    """Extract normalized tweets from a syndication timeline page.

    Returns ``[]`` for a login wall, a JS-only shell or any payload without
    tweet objects — never a fabricated object.
    """
    match = NEXT_DATA_RE.search(html or "")
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except ValueError as exc:
        logger.warning("x_next_data_unparsable handler=x_parse error=%s", exc)
        return []

    tweets: list[dict] = []
    seen: set[str] = set()
    for node in _walk(payload):
        tweet_id = str(node.get("id_str") or node.get("rest_id") or node.get("id") or "")
        text = node.get("full_text") or node.get("text") or ""
        if not tweet_id or tweet_id in seen or not text:
            continue
        seen.add(tweet_id)
        author = _handle(node) or handle
        tweets.append(
            {
                "id": tweet_id,
                "handle": author,
                "author_name": _author_name(node),
                "text": text,
                "lang": node.get("lang"),
                "created_at": node.get("created_at") or node.get("tweet_created_at") or "",
                "url": f"https://x.com/{author}/status/{tweet_id}",
                "metrics": {
                    "likes": _count(node, "favorite_count", "like_count"),
                    "retweets": _count(node, "retweet_count"),
                    "replies": _count(node, "reply_count"),
                    "quotes": _count(node, "quote_count"),
                },
            }
        )
        if len(tweets) >= limit:
            break
    return tweets
