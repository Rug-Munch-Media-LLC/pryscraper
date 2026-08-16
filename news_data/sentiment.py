"""News sentiment + entity timelines for Pry (free, no-auth sources).

Computes market/PR-relevant sentiment over GDELT news coverage using two
signals:

* **GDELT tone** — GDELT's per-article ``Tone`` field (compound ``-100..100``
  score from the article text). Fetched via the Article List CSV output
  (``mode=artlist&format=csv``), which carries a ``Tone`` column per article.
* **Lightweight keyword sentiment** — a small positive/negative lexicon
  scored over article titles. Used as the per-article fallback when GDELT
  tone is unavailable (JSON path, rate limits, missing column).

* :func:`get_sentiment` — aggregate sentiment for a query within a
  timeframe: ``{query, avg_tone, positive_pct, negative_pct, articles,
  mentions_timeline}`` with a daily ``mentions_timeline``
  (``[{date, count, avg_tone}]``).
* :func:`get_entity_timeline` — per-day breakdown for an entity
  (``[{date, articles, avg_tone, top_sources}]``), where ``top_sources`` is
  the top-5 source domains by article count for that day.

Contract
--------
* :func:`get_sentiment` — async, never raises, returns a ``dict`` (``{}`` on
  failure / no coverage).
* :func:`get_entity_timeline` — async, never raises, returns a ``list``
  (``[]`` on failure / no coverage).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from news_data.headlines import (
    _DEFAULT_LIMIT,
    _DEFAULT_TIMEFRAME,
    _GDELT_DOC_URL,
    _build_params,
    _clamp_limit,
    _fetch,
    _hostname,
    _map_json_article,
    _parse_seendate,
)

logger = logging.getLogger(__name__)

_POSITIVE_WORDS = frozenset(
    {
        "surge",
        "surges",
        "surged",
        "soar",
        "soars",
        "soared",
        "rally",
        "rallies",
        "rallied",
        "jump",
        "jumps",
        "jumped",
        "gain",
        "gains",
        "gained",
        "record",
        "records",
        "high",
        "higher",
        "highest",
        "up",
        "rise",
        "rises",
        "rose",
        "bullish",
        "bull",
        "breakout",
        "breakthrough",
        "win",
        "wins",
        "won",
        "beat",
        "beats",
        "outperform",
        "outperforms",
        "growth",
        "growing",
        "strong",
        "stronger",
        "strongest",
        "positive",
        "profit",
        "profits",
        "profitable",
        "boost",
        "boosts",
        "boosted",
        "upgrade",
        "upgrades",
        "upgraded",
        "approve",
        "approves",
        "approved",
        "approval",
        "adoption",
        "adopted",
        "launch",
        "launches",
        "launched",
        "milestone",
        "partnership",
        "partners",
        "success",
        "successful",
        "optimistic",
        "upbeat",
        "green",
        "climb",
        "climbs",
        "climbed",
        "advance",
        "advances",
        "advanced",
        "momentum",
        "demand",
        "inflow",
        "inflows",
        "accumulate",
        "accumulation",
        "support",
        "supports",
        "supported",
        "recovery",
        "recovers",
        "rebound",
        "rebounds",
        "stable",
        "stability",
        "bullishness",
        "flourish",
        "flourishing",
        "boom",
        "booming",
        "break",
        "breaks",
        "winner",
        "winners",
        "best",
        "top",
        "exceed",
        "exceeds",
        "exceeded",
        "expansion",
        "expanding",
    }
)

_NEGATIVE_WORDS = frozenset(
    {
        "crash",
        "crashes",
        "crashed",
        "plunge",
        "plunges",
        "plunged",
        "dump",
        "dumps",
        "dumped",
        "slump",
        "slumps",
        "slumped",
        "drop",
        "drops",
        "dropped",
        "fall",
        "falls",
        "fell",
        "decline",
        "declines",
        "declined",
        "low",
        "lower",
        "lowest",
        "down",
        "bearish",
        "bear",
        "selloff",
        "sell-off",
        "sell",
        "sells",
        "sold",
        "loss",
        "losses",
        "loses",
        "losing",
        "lose",
        "weak",
        "weaker",
        "weakest",
        "negative",
        "fear",
        "fears",
        "panic",
        "panics",
        "panicked",
        "worry",
        "worries",
        "worried",
        "risk",
        "risks",
        "risky",
        "fraud",
        "scam",
        "scams",
        "hack",
        "hacks",
        "hacked",
        "hacking",
        "exploit",
        "exploits",
        "exploited",
        "breach",
        "breaches",
        "breached",
        "steal",
        "steals",
        "stolen",
        "theft",
        "thief",
        "lawsuit",
        "lawsuits",
        "sue",
        "sues",
        "sued",
        "ban",
        "bans",
        "banned",
        "crackdown",
        "crackdowns",
        "warning",
        "warnings",
        "warn",
        "warns",
        "warned",
        "investigation",
        "investigations",
        "investigate",
        "investigates",
        "investigated",
        "probe",
        "probes",
        "probed",
        "fine",
        "fines",
        "fined",
        "penalty",
        "penalties",
        "sanction",
        "sanctions",
        "sanctioned",
        "collapse",
        "collapses",
        "collapsed",
        "bankrupt",
        "bankruptcy",
        "insolvent",
        "liquidation",
        "liquidated",
        "freeze",
        "freezes",
        "frozen",
        "seize",
        "seizes",
        "seized",
        "halt",
        "halts",
        "halted",
        "suspend",
        "suspends",
        "suspended",
        "suspension",
        "delist",
        "delists",
        "delisted",
        "reject",
        "rejects",
        "rejected",
        "rejection",
        "concern",
        "concerns",
        "concerned",
        "outflow",
        "outflows",
        "withdraw",
        "withdraws",
        "withdrawn",
        "withdrawal",
        "withdrawals",
        "red",
        "worst",
        "lost",
        "downfall",
        "setback",
        "setbacks",
        "trouble",
        "troubles",
        "struggle",
        "struggles",
        "struggled",
        "volatile",
        "volatility",
        "uncertainty",
        "doubt",
        "doubts",
        "doubted",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]+")


def _keyword_tone(text: str) -> float:
    """Score ``text`` -100..100 from a lightweight positive/negative lexicon.

    Ratio-based: ``100 * (pos - neg) / (pos + neg)`` when any signal words
    are present, otherwise ``0.0``.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    if not tokens:
        return 0.0
    positive = sum(1 for t in tokens if t in _POSITIVE_WORDS)
    negative = sum(1 for t in tokens if t in _NEGATIVE_WORDS)
    if positive + negative == 0:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * (positive - negative) / (positive + negative)))


def _tone_compound(tone_field: Any) -> float | None:
    """Extract GDELT's compound tone (first of the Tone column's values).

    GDELT's ``Tone`` column is a comma-separated list whose first value is
    the overall ``-100..100`` sentiment score. Returns ``None`` when the
    field is absent or not numeric.
    """
    if not isinstance(tone_field, str) or not tone_field.strip():
        return None
    first = tone_field.split(",", 1)[0].strip()
    try:
        return float(first)
    except ValueError:
        return None


def _article_tone(title: str, tone_field: Any) -> float:
    """Per-article tone: GDELT compound when present, keyword score otherwise."""
    gdelt_tone = _tone_compound(tone_field)
    if gdelt_tone is not None:
        return max(-100.0, min(100.0, gdelt_tone))
    return _keyword_tone(title)


def _csv_rows(raw: str) -> list[dict[str, Any]]:
    """Parse a GDELT artlist CSV payload into row dicts (never raises).

    GDELT prepends a UTF-8 BOM; it is stripped here so the header row is
    recognized. Missing columns simply read as ``None`` via ``.get()``.
    """
    text = raw.lstrip("\ufeff") if raw else ""
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = [row for row in reader if any((value or "").strip() for value in row.values())]
    except (csv.Error, UnicodeDecodeError, ValueError):
        return []
    return rows


def _row_to_article(row: dict[str, Any]) -> dict[str, Any]:
    """Map one CSV row to the canonical headline shape + raw tone field."""
    url = str(row.get("DocumentIdentifier") or "").strip()
    title = str(row.get("DocumentTitle") or "").strip()
    source = str(row.get("SourceCommonName") or row.get("DocumentSource") or "").strip()
    domain = _hostname(url)
    return {
        "title": title,
        "url": url,
        "source": source or domain,
        "domain": domain,
        "published": _parse_seendate(str(row.get("Seendate") or "")),
        "image": str(row.get("SocialImage") or "").strip(),
        "tone": row.get("Tone"),
    }


def _date_key(published: str) -> str:
    """Extract ``YYYY-MM-DD`` from a parsed ISO timestamp ('' when absent)."""
    return published[:10] if len(published) >= 10 else ""


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


async def _artlist(query: str, limit: int, timeframe: str) -> list[dict[str, Any]]:
    """Fetch canonical article dicts (with tone when CSV yields it).

    Primary path is GDELT's artlist CSV (carries per-article ``Tone``); when
    that fails the JSON artlist path is used (no tone → keyword fallback).
    Never raises — ``[]`` on failure.
    """
    raw = await _fetch(_GDELT_DOC_URL, _build_params(query, limit, timeframe, "csv"))
    if raw:
        rows = _csv_rows(raw)
        mapped = [_row_to_article(row) for row in rows]
        if mapped:
            return [a for a in mapped if a.get("url") or a.get("title")]

    raw_json = await _fetch(_GDELT_DOC_URL, _build_params(query, limit, timeframe, "json"))
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            return []
        if isinstance(payload, dict):
            articles = payload.get("articles")
            if isinstance(articles, list):
                mapped = [_map_json_article(a) for a in articles if isinstance(a, dict)]
                return [a for a in mapped if a][:limit]
    return []


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
