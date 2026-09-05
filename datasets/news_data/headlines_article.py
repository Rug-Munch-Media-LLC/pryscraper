"""Article extraction for Pry (full text, summary, keywords, metadata).

Reuses Pry's own anti-detection scraper (``scraper.PryScraper``) plus a
lightweight extractive summary, keyword extraction and meta-driven
authors/published date. The scraper is imported lazily so this module
stays importable standalone.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from datasets.news_data.headlines_common import _hostname

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

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


def _get_scraper() -> Any:
    """Return Pry's scraper, instantiating it lazily on first use."""
    instance = _scraper_state.get("instance")
    if instance is None:
        from pry.engine.scraper import PryScraper

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
