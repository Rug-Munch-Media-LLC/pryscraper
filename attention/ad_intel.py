"""Pry — Meta Ad Library ad intelligence (free, public, keyless).

Scrapes the public Facebook Ad Library search page and extracts active
ads for a page / keyword query:

* ``https://www.facebook.com/ads/library/?active_status=active&...&q=<query>``

The Ad Library UI is a JS app; the page HTML embeds the search results as
JSON blobs (``<script type="application/json">``) which we walk
recursively for ad-shaped dicts (``adArchiveID`` / ``adCreative`` /
``pageName``). When the page does not render structured data (login wall,
consent wall, JS shell) we return ``[]`` — the module never raises.

Contract:
    >>> ads = await search_ads("OpenAI", country="US", limit=20)
    >>> ads[0]  # {"ad_id", "page", "creative_text", "link", "start_date", "platforms"}

Reliability note: Meta frequently changes the page shell and may require
cookies / JS. The official Ad Library Graph API (page-access token,
``ad_archive_id`` fields) is the robust production path; this module is a
best-effort free fallback. Flagged [REVIEW] accordingly.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2

_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
_ARCHIVE_ID_RE = re.compile(r'"adArchiveID"\s*:\s*"(\d+)"')


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


async def _fetch_page(params: dict[str, str]) -> str:
    """Fetch the Ad Library search page with backoff (never raises)."""
    from pry.api.client import get_client

    client = await get_client()
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(
                _AD_LIBRARY_URL,
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
                follow_redirects=True,
            )
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except httpx.HTTPError as exc:  # transport / timeout / redirect errors
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("ad_library_fetch_failed", extra={"error": last_error})
    return ""


def _nested_get(data: dict[str, Any], *path: str) -> Any:
    """Safely walk a nested dict; return None when any key is missing."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _walk_dicts(obj: Any) -> Any:
    """Yield every dict (recursively) inside a parsed JSON blob."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _iter_json_blobs(html: str) -> Any:
    """Yield parsed JSON from every ``application/json`` script tag."""
    for match in _JSON_SCRIPT_RE.finditer(html):
        try:
            yield json.loads(match.group(1))
        except (ValueError, TypeError):
            continue


def _parse_entries(html: str) -> list[dict[str, Any]]:
    """Extract ad-shaped dicts from the page HTML (best-effort)."""
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for blob in _iter_json_blobs(html):
        for item in _walk_dicts(blob):
            if not isinstance(item, dict):
                continue
            is_ad = (
                "adArchiveID" in item
                or "ad_archive_id" in item
                or ("adCreative" in item and "pageName" in item)
            )
            if not is_ad:
                continue
            ad_id = str(
                item.get("adArchiveID") or item.get("ad_archive_id") or item.get("adId") or ""
            )
            if ad_id and ad_id in seen_ids:
                continue
            if ad_id:
                seen_ids.add(ad_id)
            entries.append(item)
    # Regex fallback on raw HTML (blob extraction found nothing).
    if not entries:
        for match in _ARCHIVE_ID_RE.finditer(html):
            ad_id = match.group(1)
            if ad_id in seen_ids:
                continue
            seen_ids.add(ad_id)
            entries.append({"adArchiveID": ad_id})
    return entries


def _extract_creative_text(item: dict[str, Any]) -> str:
    """Best-effort creative body text from an ad dict."""
    for path in (
        ("adCreative", "body", "text"),
        ("adCreative", "body"),
        ("adCreative", "text"),
        ("creative_text",),
        ("primaryText",),
        ("body",),
    ):
        value = _nested_get(item, *path)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:2000]
    link_data = _nested_get(item, "adCreative", "link_data", "link")
    if isinstance(link_data, str):
        return link_data[:2000]
    return ""


def _extract_platforms(item: dict[str, Any]) -> list[str]:
    """Best-effort publisher-platform list from an ad dict."""
    platforms = _nested_get(item, "publisherPlatforms")
    if isinstance(platforms, list):
        return [str(p) for p in platforms if p]
    platforms = _nested_get(item, "adCreative", "publisher_platforms")
    if isinstance(platforms, list):
        return [str(p) for p in platforms if p]
    return []


def _normalize(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize raw ad dicts into the public contract shape."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        ad_id = str(
            item.get("ad_id")
            or item.get("adId")
            or item.get("adArchiveID")
            or item.get("ad_archive_id")
            or item.get("id")
            or ""
        )
        if not ad_id or ad_id in seen:
            continue
        seen.add(ad_id)
        start_date = str(
            item.get("start_date") or item.get("adStartTime") or item.get("adCreationTime") or ""
        )
        link = (
            item.get("link")
            or item.get("linkUrl")
            or _nested_get(item, "adCreative", "link_data", "link")
            or ""
        )
        out.append(
            {
                "ad_id": ad_id,
                "page": str(item.get("page") or item.get("pageName") or item.get("page_id") or ""),
                "creative_text": _extract_creative_text(item),
                "link": str(link),
                "start_date": start_date,
                "platforms": _extract_platforms(item),
            }
        )
    return out


async def search_ads(page_name: str, country: str = "US", limit: int = 20) -> list[dict[str, Any]]:
    """Search the Meta Ad Library for active ads from a page / query.

    Never raises; returns ``[]`` on any failure.
    """
    if not page_name or not page_name.strip():
        return []
    params = {
        "active_status": "active",
        "ad_type": "all",
        "country": (country or "US").upper()[:2],
        "q": page_name.strip(),
        "search_type": "keyword_unordered",
        "media_type": "all",
    }
    try:
        html = await _fetch_page(params)
        if not html:
            return []
        ads = _normalize(_parse_entries(html))
        return ads[: max(limit, 1)]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        logger.warning(
            "ad_library_scrape_failed",
            extra={"page_name": page_name[:80], "error": str(exc)[:200]},
        )
        return []
