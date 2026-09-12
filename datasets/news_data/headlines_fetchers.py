"""HTTP fetchers + parsers for news headline collection (GDELT + RSS).

* :func:`_fetch` — resilient GET (never raises).
* :func:`_build_params` — GDELT artlist query parameters.
* :func:`_parse_rss` — generic RSS/Atom parser producing canonical
  headline dicts.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from datasets.news_data.headlines_common import (
    _GDELT_DOC_URL,
    _HEADERS,
    _TIMEOUT,
    _clamp_limit,
    _hostname,
    _parse_seendate,
    _sanitize_timeframe,
)

logger = logging.getLogger(__name__)


def _map_json_article(article: dict[str, Any]) -> dict[str, Any]:
    """Map one GDELT JSON artlist record to the canonical headline shape.

    GDELT JSON articles carry ``url, title, seendate, socialimage, domain,
    language, sourcecountry`` — there is no human-readable source name, so
    ``source`` falls back to the GDELT ``domain`` field.
    """
    title = str(article.get("title") or "").strip()
    url = str(article.get("url") or "").strip()
    if not title and not url:
        return {}
    domain = str(article.get("domain") or "").strip() or _hostname(url)
    return {
        "title": title,
        "url": url,
        "source": domain,
        "domain": domain,
        "published": _parse_seendate(str(article.get("seendate") or "")),
        "image": str(article.get("socialimage") or "").strip(),
    }


def _local_name(tag: str) -> str:
    """Strip an XML namespace prefix from an ElementTree tag name."""
    return tag.rsplit("}", 1)[-1]


def _rss_item_text(item: ET.Element, child: str) -> str:
    """Return the text of a direct RSS child element ('' when absent)."""
    for sub in item:
        if _local_name(sub.tag) == child and sub.text:
            return sub.text.strip()
    return ""


def _rss_item_image(item: ET.Element) -> str:
    """Best-effort image URL from an RSS item (enclosure / media:content)."""
    for sub in item.iter():
        name = _local_name(sub.tag)
        if name in {"enclosure", "content"}:
            url = (sub.get("url") or "").strip()
            if url:
                return url
    return ""


def _parse_rss_date(pub_date: str) -> datetime | None:
    """Parse an RSS ``pubDate`` (RFC 2822 or ISO-8601) to a datetime, or None."""
    try:
        parsed = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(pub_date)
        except (TypeError, ValueError):
            return None
    return parsed


def _parse_rss(text: str) -> list[dict[str, Any]]:
    """Parse an RSS/Atom feed into canonical headline dicts (never raises).

    Works with any well-formed RSS/Atom XML: GDELT ``format=rss`` feeds and
    generic news feeds share the same item-level fields.
    """
    try:
        root = ET.fromstring(text)  # nosec B314 — stdlib ET, read-only parse of fetched text
    except (ET.ParseError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        title = _rss_item_text(item, "title")
        url = _rss_item_text(item, "link") or _rss_item_text(item, "guid")
        if not title and not url:
            continue
        published = ""
        pub_date = _rss_item_text(item, "pubDate")
        if pub_date:
            parsed = _parse_rss_date(pub_date)
            if parsed is not None:
                published = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        domain = _hostname(url)
        source = _rss_item_text(item, "source") or domain
        out.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "domain": domain,
                "published": published,
                "image": _rss_item_image(item),
            }
        )
    return out


async def _fetch(url: str, params: dict[str, str]) -> str:
    """GET a URL; never raises ('' on failure)."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            return ""
        return resp.text
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("news_fetch_failed", extra={"url": url[:120], "error": str(exc)[:120]})
        return ""


def _build_params(query: str, limit: int, timeframe: str, fmt: str) -> dict[str, str]:
    return {
        "query": query,
        "mode": "artlist",
        "format": fmt,
        "timespan": _sanitize_timeframe(timeframe),
        "maxrecords": str(limit),
    }


async def get_headlines(
    query: str, limit: int = 20, timeframe: str = "24h"
) -> list[dict[str, Any]]:
    """Fetch recent headlines matching ``query``.

    Primary path is GDELT's JSON Article List; on any failure the same query
    is retried via GDELT's RSS output. Never raises — ``[]`` when nothing
    could be fetched or no coverage exists.

    Args:
        query: Free-text search term (required, non-empty).
        limit: Max headlines to return (clamped to GDELT's 250 cap).
        timeframe: GDELT timespan (e.g. ``"24h"``, ``"7d"``, ``"1w"``).

    Returns:
        List of ``{title, url, source, domain, published, image}`` dicts.
    """
    if not query or not str(query).strip():
        return []
    limit = _clamp_limit(limit)

    raw = await _fetch(_GDELT_DOC_URL, _build_params(query, limit, timeframe, "json"))
    if raw:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            articles = payload.get("articles")
            if isinstance(articles, list):
                mapped = [_map_json_article(a) for a in articles if isinstance(a, dict)]
                return [a for a in mapped if a][:limit]

    # RSS fallback — same query, GDELT's RSS output (or any generic feed).
    raw_rss = await _fetch(_GDELT_DOC_URL, _build_params(query, limit, timeframe, "rss"))
    if raw_rss:
        mapped = _parse_rss(raw_rss)
        if mapped:
            return mapped[:limit]
    logger.warning("news_headlines_empty", extra={"query": str(query)[:120]})
    return []
