"""Social follower metrics for public profiles: Instagram, TikTok, X, YouTube.

Sources (all free, no auth):

* **instagram** — public profile page ``https://www.instagram.com/{handle}/``.
  Parse the ``og:description`` meta tag ("1.2M Followers, 345 Following,
  1,234 Posts"). Instagram serves a login wall to datacenter IPs, but the
  meta tags are usually present in the initial HTML even when the feed is
  gated.
* **tiktok** — ``https://www.tiktok.com/@{handle}``. Parse the embedded
  ``__UNIVERSAL_DATA_FOR_REHYDRATION__`` JSON (``userInfo.stats``:
  follower/following/video counts + total hearts). Heavily JS-challenged;
  frequently returns a challenge page with no hydration data.
* **twitter / x** — ``https://x.com/{handle}``. Parse ``og:description``
  ("10K Followers, 200 Following, 5K Posts ..."). X is behind a login
  wall for unauthenticated clients; meta tags are often present, and
  sometimes absent entirely.
* **youtube** — ``https://www.youtube.com/@{handle}``. Parse the embedded
  ``ytInitialData`` JSON strings (``subscriberCountText``,
  ``videoCountText``, ``viewCountText``).

Reliability (read before shipping)
----------------------------------
Every platform aggressively blocks datacenter traffic. Results degrade to
**partial data**: all keys are always present, unknown metrics are
``None``, derived metrics (``avg_engagement``, ``engagement_rate``,
``fake_follower_estimate``) are computed only when their inputs are known.
This module performs **no** anti-bot bypass — if the platform serves a
challenge, the honest result is ``None`` fields, never fabricated numbers.

``avg_engagement`` is a proxy: TikTok total-hearts ÷ videos, YouTube
total-views ÷ videos (views are the only public engagement signal).
``fake_follower_estimate`` is a deterministic 0.0-1.0 heuristic band based
on the engagement-to-following ratio — **not** a real fraud measurement.

Contract
--------
* :func:`get_social_metrics` — async, never raises. Returns a dict with
  keys ``{handle, platform, followers, following, posts, avg_engagement,
  engagement_rate, fake_follower_estimate}`` (``None`` for unknown), or
  ``{}`` for invalid handle/platform.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PLATFORMS = ("instagram", "tiktok", "twitter", "x", "youtube")

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

_TIKTOK_HYDRATION_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.DOTALL
)
_META_PROP_RE = re.compile(r'<meta[^>]+property="([^"]*)"[^>]*content="([^"]*)"', re.DOTALL)

_FOLLOWERS_RE = re.compile(r"([\d.,]+[KM]?)\s*Followers")
_FOLLOWING_RE = re.compile(r"([\d.,]+[KM]?)\s*Following")
_POSTS_RE = re.compile(r"([\d.,]+[KM]?)\s*Posts")
_COUNT_TEXT_RE = re.compile(r"([\d.,]+)\s*([KM]?)")


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    if attempt <= 0 or RETRY_BASE <= 0 or MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(MAX_BACKOFF, RETRY_BASE * (2**attempt)))


async def _fetch(url: str) -> str:
    """GET a profile page with bounded backoff retries; '' on failure."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("social_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


def _parse_count(text: str | None) -> int | None:
    """Parse '1.2M' / '350K' / '1,234' into an int; None when unparsable."""
    if not text:
        return None
    s = text.strip()
    multiplier = 1
    if s.endswith(("M", "m")):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith(("K", "k")):
        multiplier = 1_000
        s = s[:-1]
    s = s.replace(",", "")
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return None


def _count_from_text(text: str | None) -> int | None:
    """Parse counts embedded in phrases like '1.23M subscribers'."""
    if not text:
        return None
    match = _COUNT_TEXT_RE.search(text)
    if not match:
        return None
    return _parse_count(match.group(1) + (match.group(2) or "").upper())


def _to_int(value: Any) -> int | None:
    """Coerce a JSON value to int; None when not integral."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace(" ", "")
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _walk_dicts(obj: Any) -> Any:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _deep_first(obj: Any, keys: tuple[str, ...]) -> Any:
    """First non-None value found for any of ``keys`` at any depth."""
    for d in _walk_dicts(obj):
        for key in keys:
            value = d.get(key)
            if value is not None:
                return value
    return None


def _meta_content(raw: str, prop: str) -> str | None:
    """Return the ``content`` of the first ``<meta property="...">`` tag."""
    for p, content in _META_PROP_RE.findall(raw):
        if p == prop and content.strip():
            return content.strip()
    return None


# ── derived metrics ────────────────────────────────────────────────────


def estimate_fake_followers(
    followers: int | None, avg_engagement: float | int | None
) -> float | None:
    """Heuristic 0.0-1.0 fake-follower estimate from engagement signals.

    Deterministic band mapping on the engagement-to-following ratio — a
    screening heuristic, NOT a real fraud measurement. Unknown inputs
    (missing followers or engagement) return ``None``.

    Bands (engagement rate = avg_engagement / followers):
        >= 5%      -> 0.05   (healthy)
        2-5%       -> 0.15
        1-2%       -> 0.30
        0.5-1%     -> 0.50
        0.1-0.5%   -> 0.70
        < 0.1%     -> 0.90   (suspicious: many followers, little engagement)
    """
    if not followers or followers <= 0 or avg_engagement is None:
        return None
    rate = float(avg_engagement) / float(followers)
    if rate >= 0.05:
        return 0.05
    if rate >= 0.02:
        return 0.15
    if rate >= 0.01:
        return 0.30
    if rate >= 0.005:
        return 0.50
    if rate >= 0.001:
        return 0.70
    return 0.90


def _compose_metrics(
    handle: str,
    platform: str,
    *,
    followers: int | None = None,
    following: int | None = None,
    posts: int | None = None,
    avg_engagement: float | None = None,
) -> dict[str, Any]:
    """Build the canonical metrics dict, deriving rate/estimate fields."""
    engagement_rate: float | None = None
    if avg_engagement is not None and followers and followers > 0:
        engagement_rate = round(avg_engagement / followers, 6)
    return {
        "handle": handle,
        "platform": platform,
        "followers": followers,
        "following": following,
        "posts": posts,
        "avg_engagement": avg_engagement,
        "engagement_rate": engagement_rate,
        "fake_follower_estimate": estimate_fake_followers(followers, avg_engagement),
    }


# ── per-platform scrapers ──────────────────────────────────────────────


async def _instagram_metrics(handle: str, platform: str) -> dict[str, Any]:
    raw = await _fetch(f"https://www.instagram.com/{handle}/")
    description = _meta_content(raw, "og:description") or ""
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    if description:
        match = _FOLLOWERS_RE.search(description)
        if match:
            followers = _parse_count(match.group(1))
        match = _FOLLOWING_RE.search(description)
        if match:
            following = _parse_count(match.group(1))
        match = _POSTS_RE.search(description)
        if match:
            posts = _parse_count(match.group(1))
    return _compose_metrics(handle, platform, followers=followers, following=following, posts=posts)


async def _tiktok_metrics(handle: str, platform: str) -> dict[str, Any]:
    raw = await _fetch(f"https://www.tiktok.com/@{handle}")
    match = _TIKTOK_HYDRATION_RE.search(raw)
    stats: dict[str, Any] = {}
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            data = None
        if data is not None:
            found = _deep_first(data, ("stats",))
            if isinstance(found, dict):
                stats = found
    followers = _to_int(stats.get("followerCount"))
    following = _to_int(stats.get("followingCount"))
    posts = _to_int(stats.get("videoCount"))
    likes = _to_int(stats.get("heartCount"))
    avg_engagement: float | None = None
    if likes is not None and posts and posts > 0:
        avg_engagement = round(likes / posts, 2)
    return _compose_metrics(
        handle,
        platform,
        followers=followers,
        following=following,
        posts=posts,
        avg_engagement=avg_engagement,
    )


async def _twitter_metrics(handle: str, platform: str) -> dict[str, Any]:
    raw = await _fetch(f"https://x.com/{handle}")
    description = _meta_content(raw, "og:description") or ""
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    if description:
        match = _FOLLOWERS_RE.search(description)
        if match:
            followers = _parse_count(match.group(1))
        match = _FOLLOWING_RE.search(description)
        if match:
            following = _parse_count(match.group(1))
        match = _POSTS_RE.search(description)
        if match:
            posts = _parse_count(match.group(1))
    return _compose_metrics(handle, platform, followers=followers, following=following, posts=posts)


async def _youtube_metrics(handle: str, platform: str) -> dict[str, Any]:
    raw = await _fetch(f"https://www.youtube.com/@{handle}")
    subscribers = _count_from_text(_yt_metadata(raw, "subscriberCountText"))
    videos = _count_from_text(_yt_metadata(raw, "videoCountText"))
    views = _count_from_text(_yt_metadata(raw, "viewCountText"))
    avg_engagement: float | None = None
    if views is not None and videos and videos > 0:
        avg_engagement = round(views / videos, 2)
    return _compose_metrics(
        handle,
        platform,
        followers=subscribers,
        following=None,
        posts=videos,
        avg_engagement=avg_engagement,
    )


def _yt_metadata(raw: str, key: str) -> str | None:
    """Pull a flat ``{"content": "..."}`` value like ``subscriberCountText``."""
    pattern = re.compile(rf'"{re.escape(key)}":\s*\{{[^}}]*?"content"\s*:\s*"([^"]+)"')
    match = pattern.search(raw)
    if not match:
        return None
    return match.group(1)


# ── public API ─────────────────────────────────────────────────────────


async def get_social_metrics(handle: str, platform: str = "instagram") -> dict[str, Any]:
    """Return public follower metrics for a profile. Async, never raises.

    ``platform`` is one of ``instagram``, ``tiktok``, ``twitter``, ``x``,
    ``youtube`` (``x`` and ``twitter`` hit the same endpoint).

    Returns a dict with keys ``{handle, platform, followers, following,
    posts, avg_engagement, engagement_rate, fake_follower_estimate}``
    (``None`` for unknown metrics — partial data on login walls / blocks),
    or ``{}`` for an invalid handle or platform.
    """
    clean_handle = (handle or "").strip().strip("@")
    clean_platform = (platform or "").strip().lower()
    if not clean_handle or clean_platform not in PLATFORMS:
        return {}
    impl = {
        "instagram": _instagram_metrics,
        "tiktok": _tiktok_metrics,
        "twitter": _twitter_metrics,
        "x": _twitter_metrics,
        "youtube": _youtube_metrics,
    }[clean_platform]
    try:
        return await impl(clean_handle, clean_platform)
    except Exception:  # public API boundary: never-raise contract (mirrors gov_data/recalls.py)
        logger.exception(
            "social_metrics_failed", extra={"handle": clean_handle, "platform": clean_platform}
        )
        return _compose_metrics(clean_handle, clean_platform)
