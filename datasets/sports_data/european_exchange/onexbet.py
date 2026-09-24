"""1xBet LineFeed payload decoder and fetcher."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import base64
import gzip
import json
import zlib
from typing import Any
from urllib.parse import urlencode

import httpx

import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from datasets.sports_data.european_common import (
    _1XBET_LEAGUE_KEYWORDS,
    _1XBET_SPORTS,
    EUROPEAN_BOOKS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.european_exchange.common import _event_label, logger
from datasets.sports_data.offshore import _fetch_json_geo
from datasets.sports_data.sources import _as_text, _to_float


def _decode_1xbet_payload(payload: dict[str, Any]) -> Any | None:
    """Decode the 1xBet ``Value`` field (base64 -> gzip/zlib -> JSON)."""
    value = payload.get("Value")
    if not isinstance(value, str) or not value:
        return None
    try:
        raw = base64.b64decode(value)
    except (ValueError, TypeError):
        return None
    for decompressor in (gzip.decompress, zlib.decompress):
        try:
            return json.loads(decompressor(raw).decode("utf-8", "replace"))
        except (OSError, zlib.error, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def _parse_1xbet_payload(data: Any, canonical: str, keyword: str | None) -> list[dict[str, Any]]:
    """Map the decoded LineFeed JSON onto h2h records.

    Structure: ``L`` = leagues [{id, I: name}], ``E`` = events
    [{id, L: league id, S: start, T: [{N: team}...], G: [group]}] where the
    first group (``G == "1"``) holds the match-winner outcomes
    (``T`` in {1, X, 2}, ``P: {"1": decimal}``).
    """
    if not isinstance(data, dict):
        return []
    leagues: dict[Any, str] = {}
    for league in data.get("L") or []:
        if isinstance(league, dict) and isinstance(league.get("id"), int):
            leagues[league["id"]] = str(league.get("I") or "")
    records: list[dict[str, Any]] = []
    for event in data.get("E") or []:
        if not isinstance(event, dict):
            continue
        league_name = leagues.get(event.get("L"))
        if keyword and league_name and keyword not in league_name.lower():
            continue
        teams_raw = event.get("T") or []
        teams = [str(t.get("N") or "") for t in teams_raw if isinstance(t, dict) and t.get("N")]
        if len(teams) < 2:
            continue
        away, home = teams[0], teams[1]  # 1xBet lists participants away-first
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        outcomes: dict[str, float] = {}
        groups = event.get("G") or []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("G") or "") != "1":
                continue
            for outcome in group.get("E") or []:
                if not isinstance(outcome, dict):
                    continue
                key = str(outcome.get("T") or "")
                price = outcome.get("P")
                if not isinstance(price, dict):
                    continue
                value = _to_float(price.get("1"))
                if value is not None and value > 1:
                    outcomes[key] = round(value, 2)
            break
        home_odds = outcomes.get("1")
        away_odds = outcomes.get("2")
        if home_odds is None or away_odds is None:
            continue
        records.append(
            sources._record(  # type: ignore[attr-defined]
                sport=canonical,
                event=event_label,
                event_id=str(event.get("id")),
                market="h2h",
                book="1xbet",
                bookmaker="1xBet",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                draw_odds=outcomes.get("X"),
                last_update=_as_text(event.get("S")),
                source="european",
            )
        )
    return records


async def fetch_1xbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 1xBet odds for one sport via the internal LineFeed endpoint."""
    name = "1xbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        sport_id = _1XBET_SPORTS.get(canonical)
        if sport_id is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        query = urlencode(
            {
                "sport": sport_id,
                "lng": "en",
                "tf": "2200000",
                "tz": "3",
                "mode": "4",
                "country": "1",
            }
        )
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/Get1x2_VZip?{query}"
        payload = await _fetch_json_geo(url)
        if not isinstance(payload, dict):
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        data = _decode_1xbet_payload(payload)
        records = _parse_1xbet_payload(data, canonical, _1XBET_LEAGUE_KEYWORDS.get(canonical))
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
