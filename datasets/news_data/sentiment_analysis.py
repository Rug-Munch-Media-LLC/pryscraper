"""Sentiment aggregation + daily timeline analysis over news articles.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from datasets.news_data.headlines import _DEFAULT_LIMIT, _DEFAULT_TIMEFRAME, _clamp_limit
from datasets.news_data.sentiment_common import _article_tone, _date_key

if TYPE_CHECKING:
    from collections.abc import Iterable


def _bucket_daily(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bucket article items by day into ``[{date, count, avg_tone, ...}]``.

    ``items`` are canonical article dicts that may carry a ``tone`` key (the
    raw GDELT Tone field) and a ``title`` used for keyword fallback. Missing
    dates are dropped; dates are sorted ascending.
    """
    per_day: dict[str, list[float]] = defaultdict(list)
    for item in items:
        date_key = _date_key(str(item.get("published") or ""))
        if not date_key:
            continue
        per_day[date_key].append(_article_tone(str(item.get("title") or ""), item.get("tone")))
    out: list[dict[str, Any]] = []
    for date_key in sorted(per_day):
        tones = per_day[date_key]
        out.append(
            {
                "date": date_key,
                "count": len(tones),
                "avg_tone": round(sum(tones) / len(tones), 2),
            }
        )
    return out


def _sources_per_day(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Map date -> {source domain -> article count} for timeline top sources."""
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        date_key = _date_key(str(item.get("published") or ""))
        source = str(item.get("source") or "").strip()
        if date_key and source:
            per_day[date_key][source] += 1
    return per_day


def _top_sources(counts: dict[str, int], top_n: int = 5) -> list[dict[str, Any]]:
    """Top-N sources by article count: ``[{source, count}]``.

    Descending by count, ascending by name for ties (stable + readable).
    """
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [{"source": source, "count": count} for source, count in ranked[:top_n]]


# ── public API ─────────────────────────────────────────────────────────


async def get_sentiment(
    query: str, timeframe: str = _DEFAULT_TIMEFRAME, limit: int = _DEFAULT_LIMIT
) -> dict[str, Any]:
    """Aggregate sentiment for ``query`` over the given ``timeframe``.

    Args:
        query: Free-text search term (required, non-empty).
        timeframe: GDELT timespan (e.g. ``"24h"``, ``"7d"``).
        limit: Max articles to pull for the aggregate (clamped 1..250).

    Returns:
        ``{query, avg_tone, positive_pct, negative_pct, articles,
        mentions_timeline}`` — ``{}`` on failure / no coverage.
    """
    from datasets.news_data.sentiment_fetchers import _artlist

    if not query or not str(query).strip():
        return {}
    articles = await _artlist(str(query).strip(), _clamp_limit(limit), timeframe)
    if not articles:
        return {}
    tones = [_article_tone(str(a.get("title") or ""), a.get("tone")) for a in articles]
    total = len(tones)
    positive = sum(1 for tone in tones if tone > 0)
    negative = sum(1 for tone in tones if tone < 0)
    return {
        "query": str(query).strip(),
        "avg_tone": round(sum(tones) / total, 2),
        "positive_pct": round(100.0 * positive / total, 1),
        "negative_pct": round(100.0 * negative / total, 1),
        "articles": total,
        "mentions_timeline": _bucket_daily(articles),
    }


async def get_entity_timeline(
    entity: str, timeframe: str = "7d", limit: int = _DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """Per-day news timeline for an entity with tone + top sources.

    Args:
        entity: Entity / search term (e.g. a ticker, project or person).
        timeframe: GDELT timespan (default ``"7d"``).
        limit: Max articles to pull (clamped 1..250).

    Returns:
        ``[{date, articles, avg_tone, top_sources}]`` ascending by date —
        ``[]`` on failure / no coverage. ``top_sources`` is the top-5
        ``[{source, count}]`` for that day.
    """
    from datasets.news_data.sentiment_fetchers import _artlist

    if not entity or not str(entity).strip():
        return []
    articles = await _artlist(str(entity).strip(), _clamp_limit(limit), timeframe)
    if not articles:
        return []
    daily = _bucket_daily(articles)
    by_date: dict[str, dict[str, Any]] = {
        entry["date"]: {
            "date": entry["date"],
            "articles": entry["count"],
            "avg_tone": entry["avg_tone"],
        }
        for entry in daily
    }
    sources = _sources_per_day(articles)
    for date_key, counts in sources.items():
        if date_key in by_date:
            by_date[date_key]["top_sources"] = _top_sources(counts)
        else:
            by_date[date_key] = {
                "date": date_key,
                "articles": 0,
                "avg_tone": 0.0,
                "top_sources": _top_sources(counts),
            }
    return [by_date[date_key] for date_key in sorted(by_date)]
