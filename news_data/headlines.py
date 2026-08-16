"""News headlines + article extraction for Pry (real-time, free sources).

Fetches real-time news headlines for trading/PR use-cases from the **GDELT
DOC 2.0 API** (free, no auth, no key) with a GDELT **RSS** fallback:

* :func:`get_headlines` — query GDELT's Article List (``mode=artlist``,
  ``format=json``) for matching headlines within a timeframe, mapped to
  ``{title, url, source, domain, published, image}``. If the JSON path fails
  (HTTP error, rate limit, malformed payload) the same query is retried with
  ``format=rss`` and parsed with the stdlib XML parser — no third-party RSS
  dependency needed.
* :func:`get_article` — extracts full article text by reusing Pry's own
  anti-detection scraper (``scraper.PryScraper``), plus a lightweight
  extractive summary, keyword extraction and meta-driven authors/published
  date. The scraper is imported lazily so this module stays importable
  standalone.

Contract
--------
* :func:`get_headlines` — async, never raises, returns a ``list`` (``[]`` on
  failure / no coverage).
* :func:`get_article` — async, never raises, returns a ``dict`` (``{}`` on
  invalid URL / scrape failure).

Both degrade honestly: no fake headlines, no fake article bodies.

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
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

_MAX_LIMIT = 250  # GDELT MAXRECORDS cap (artlist mode)
_DEFAULT_LIMIT = 20
_DEFAULT_TIMEFRAME = "24h"

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,application/rss+xml,text/xml,text/html;q=0.9,*/*;q=0.8",
}

_TIMEFRAME_RE = re.compile(r"^\d+(min|h|hours|d|days|w|weeks|m|months)$")
_SEENDATE_RE = re.compile(r"^(\d{8})T(\d{6})Z$")

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "have",
        "will",
        "were",
        "their",
        "they",
        "what",
        "when",
        "where",
        "which",
        "while",
        "after",
        "before",
        "about",
        "into",
        "over",
        "under",
        "them",
        "then",
        "than",
        "there",
        "these",
        "those",
        "your",
        "you",
        "its",
        "has",
        "had",
        "not",
        "but",
        "are",
        "was",
        "been",
        "being",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "can",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "too",
        "very",
        "just",
        "also",
        "yet",
        "one",
        "two",
        "new",
        "says",
        "said",
        "say",
        "per",
        "via",
        "https",
        "http",
        "com",
    }
)

# Scraper singleton — created lazily so module import stays light. Stored in
# a dict so the lazy setter needs no ``global`` statement.
_scraper_state: dict[str, Any] = {"instance": None}


# ── low-level helpers ──────────────────────────────────────────────────


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _sanitize_timeframe(timeframe: Any) -> str:
    """Return a GDELT ``timespan`` value, or the default when malformed."""
    if isinstance(timeframe, str) and _TIMEFRAME_RE.match(timeframe.strip()):
        return timeframe.strip()
    return _DEFAULT_TIMEFRAME


def _hostname(url: str) -> str:
    """Return the bare hostname of a URL ('' when unparseable)."""
    try:
        return urlparse(url).netloc.lower() or ""
    except ValueError:
        return ""


def _parse_seendate(value: str) -> str:
    """Convert GDELT ``YYYYMMDDTHHMMSSZ`` to ``YYYY-MM-DDTHH:MM:SSZ``.

    Returns ``""`` when the value is not in GDELT's format (e.g. RSS
    ``pubDate`` is handled separately).
    """
    match = _SEENDATE_RE.match(value.strip() if isinstance(value, str) else "")
    if not match:
        return ""
    date_part, time_part = match.groups()
    try:
        dt = datetime.strptime(f"{date_part}T{time_part}Z", "%Y%m%dT%H%M%SZ")
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        root = ET.fromstring(text)  # noqa: S314 — stdlib xml.etree (no defusedxml dep); read-only
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


# ── public API ─────────────────────────────────────────────────────────


async def get_headlines(
    query: str, limit: int = _DEFAULT_LIMIT, timeframe: str = _DEFAULT_TIMEFRAME
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


def _get_scraper() -> Any:
    """Return Pry's scraper, instantiating it lazily on first use."""
    instance = _scraper_state.get("instance")
    if instance is None:
        from scraper import PryScraper

        instance = PryScraper()
        _scraper_state["instance"] = instance
    return instance


async def _scrape_page(url: str) -> dict[str, Any]:
    """Run Pry's own scraper against ``url``; never raises (``{}`` on failure)."""
    try:
        scraper = _get_scraper()
        result = await scraper.scrape(url)
        return result if isinstance(result, dict) else {}
    except Exception:  # noqa: BLE001 — never-raise contract; scraper raises many types
        logger.warning("news_article_scrape_failed", extra={"url": url[:200]})
        return {}


def _meta_content(raw_html: str, names: Iterable[str]) -> list[str]:
    """Collect the ``content`` of the first matching meta tags (case-insensitive).

    Handles both ``<meta name="author" content="...">`` and
    ``<meta property="article:author" content="...">`` forms.
    """
    wanted = {name.lower() for name in names}
    found: list[str] = []
    for match in re.finditer(r"<meta\b([^>]*)>", raw_html, re.IGNORECASE):
        attrs = match.group(1)
        key_match = re.search(
            r'(?:name|property|itemprop)\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE
        )
        if not key_match or key_match.group(1).strip().lower() not in wanted:
            continue
        content_match = re.search(r'content\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        if content_match and content_match.group(1).strip():
            found.append(content_match.group(1).strip())
    return found


def _extract_authors(raw_html: str) -> list[str]:
    """Best-effort author list from page meta tags."""
    authors = _meta_content(
        raw_html, ("author", "article:author", "byl", "byline", "parsely-author")
    )
    deduped: list[str] = []
    for author in authors:
        # "article:author" is often a URL — keep only the trailing label.
        if author.startswith(("http://", "https://")):
            label = _hostname(author) or author
        else:
            label = author
        if label and label not in deduped:
            deduped.append(label)
    return deduped


def _extract_published(raw_html: str) -> str:
    """Best-effort publish timestamp from page meta tags (ISO-8601 or '')."""
    for value in _meta_content(
        raw_html,
        (
            "article:published_time",
            "datepublished",
            "date",
            "publish-date",
            "parsely-pub-date",
        ),
    ):
        cleaned = value.strip().rstrip("Z")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


def _summarize(text: str, max_chars: int = 350) -> str:
    """Extractive summary: the first sentences of ``text`` capped at ~350 chars."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = ""
    for sentence in sentences:
        if summary and len(summary) + len(sentence) + 1 > max_chars:
            break
        summary = f"{summary} {sentence}".strip()
    return summary if summary else cleaned[:max_chars]


def _keywords(text: str, top_n: int = 10) -> list[str]:
    """Top frequent tokens from ``text`` (stopword-filtered, len >= 4)."""
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{3,}", text.lower())
    counts: dict[str, int] = {}
    for token in tokens:
        if token not in _STOPWORDS:
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)
    return [word for word, _count in ranked[:top_n]]


async def get_article(url: str) -> dict[str, Any]:
    """Extract a full article (text + summary + metadata) from ``url``.

    Reuses Pry's own anti-detection scraper (``scraper.PryScraper``) for the
    fetch/extraction, then adds a lightweight extractive summary, keyword
    extraction and meta-driven authors/published date. Never raises — ``{}``
    on invalid URL, scrape failure or missing content.

    Returns:
        ``{title, text, summary, keywords, authors, published}`` dict.
    """
    if not url or not str(url).strip().startswith(("http://", "https://")):
        return {}
    result = await _scrape_page(str(url).strip())
    if not isinstance(result, dict) or result.get("status") != "ok":
        return {}
    raw_html = str(result.get("raw_html") or "")
    text = str(result.get("content") or "").strip()
    if not text:
        return {}
    return {
        "title": str(result.get("title") or "").strip(),
        "text": text,
        "summary": _summarize(text),
        "keywords": _keywords(text),
        "authors": _extract_authors(raw_html),
        "published": _extract_published(raw_html),
    }
