"""Single tweet via the public embed JSON (no auth).

Surface: ``https://cdn.syndication.twimg.com/tweet-result?id=<id>&lang=en``
Verified from Talos 2026-10-25: HTTP 200, ~920 B ``application/json`` with
``text``, ``created_at``, ``favorite_count`` and ``user``. A soft-blocked
request answers 200 with an empty ``{}`` body, which this adapter refuses
rather than reporting a tweet with no text.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from pry.actors.x_envelope import envelope, refusal

logger = logging.getLogger(__name__)

SOURCE = "cdn.syndication.tweet-result"
URL = "https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ID_RE = re.compile(r"^\d{1,25}$")


def fetch_tweet(
    tweet_id: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> dict:
    """Fetch one tweet by id, or an honest refusal envelope."""
    tweet_id = str(tweet_id or "").strip()
    if not ID_RE.match(tweet_id):
        return refusal(SOURCE, "no_data", detail="invalid tweet id")

    owns_client = client is None
    client = client or httpx.Client(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        response = client.get(URL.format(tweet_id=tweet_id))
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning("x_tweet_transport_failure handler=x_tweet error=%s", exc)
        return refusal(SOURCE, "blocked.challenge", detail=f"transport: {type(exc).__name__}")
    finally:
        if owns_client:
            client.close()

    status = response.status_code
    if status == 429:
        return refusal(SOURCE, "blocked.ratelimit", http_status=429)
    if status in (401, 403):
        return refusal(SOURCE, "blocked.auth", http_status=status)

    try:
        payload = json.loads(response.text or "{}")
    except ValueError as exc:
        logger.warning("x_tweet_body_not_json handler=x_tweet error=%s", exc)
        return refusal(SOURCE, "no_data", http_status=status, detail="non-JSON body")
    if not isinstance(payload, dict) or not payload:
        return refusal(
            SOURCE,
            "blocked.ratelimit",
            http_status=status,
            detail="empty JSON body (soft block observed on this surface)",
        )
    if payload.get("__typename") not in (None, "Tweet"):
        return refusal(SOURCE, "no_data", http_status=status, detail="not a tweet")
    if not payload.get("text"):
        return refusal(SOURCE, "no_data", http_status=status, detail="tweet has no text")

    user = payload.get("user") or {}
    return envelope(
        ok=True,
        source=SOURCE,
        http_status=status,
        data={
            "id": str(payload.get("id_str") or tweet_id),
            "handle": str(user.get("screen_name") or ""),
            "author_name": str(user.get("name") or ""),
            "text": str(payload.get("text")),
            "lang": payload.get("lang"),
            "created_at": payload.get("created_at"),
            "url": f"https://x.com/{user.get('screen_name') or 'i'}/status/{tweet_id}",
            "metrics": {
                "likes": int(payload.get("favorite_count") or 0),
                "retweets": int(payload.get("retweet_count") or 0),
                "replies": int(payload.get("conversation_count") or 0),
                "quotes": int(payload.get("quote_count") or 0),
            },
        },
    )
