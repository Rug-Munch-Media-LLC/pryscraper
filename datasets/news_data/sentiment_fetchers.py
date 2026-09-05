"""GDELT artlist fetching + CSV/JSON parsing for news sentiment.

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
from typing import Any

from datasets.news_data.headlines import (
    _GDELT_DOC_URL,
    _build_params,
    _fetch,
    _hostname,
    _map_json_article,
    _parse_seendate,
)


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
