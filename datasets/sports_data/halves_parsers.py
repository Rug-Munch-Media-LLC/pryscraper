"""Parsers mapping Odds API period payloads onto canonical records.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from datasets.sports_data.halves_common import (
    _as_text,
    _canonical_book,
    _event_label,
    _period_label,
    _to_float,
)


def _map_period_event(
    raw: dict[str, Any], sport_slug: str, book_slug: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API period-markets payload onto period records."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away)
    event_id = _as_text(raw.get("id"))
    if not event or not event_id:
        return []
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        title = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        if not title:
            continue
        if _canonical_book is not None:
            book = _canonical_book(_as_text(bk.get("key")) or title)
        else:
            book = str(title).strip().lower()
        if book_slug is not None and book != book_slug:
            continue
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            period = _period_label(market_key)
            if period is None:
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            record = _parse_period_outcomes(
                outcomes, market_key, period, home, away, event, event_id, sport_slug, book
            )
            if record is not None:
                records.append(record)
    return records


def _parse_period_outcomes(
    outcomes: list[Any],
    market_key: str,
    period: str,
    home: str | None,
    away: str | None,
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> dict[str, Any] | None:
    """Parse one period market's outcomes into a canonical record."""
    base: dict[str, Any] = {
        "event": event,
        "event_id": event_id,
        "sport": sport_slug,
        "period": period,
        "market": market_key,
        "home_odds": None,
        "away_odds": None,
        "total": None,
        "line": None,
        "book": book,
        "source": "the_odds_api",
    }
    suffix = market_key.split("_", 1)[1] if "_" in market_key else ""
    if suffix == "totals":
        over_odds = under_odds = None
        total: float | None = None
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            label = str(outcome.get("name") or "").strip().lower()
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if price is None:
                continue
            if label in {"over", "o"}:
                over_odds, total = price, point
            elif label in {"under", "u"}:
                under_odds, total = price, point
        if over_odds is None and under_odds is None:
            return None
        base["home_odds"] = over_odds
        base["away_odds"] = under_odds
        base["total"] = total
        return base
    if suffix == "spreads":
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            team_name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if team_name is None or price is None or point is None:
                continue
            if home and team_name.casefold() == home.casefold():
                base["home_odds"] = price
                base["line"] = point
            elif away and team_name.casefold() == away.casefold():
                base["away_odds"] = price
                if base["line"] is None:
                    base["line"] = -point
        if base["home_odds"] is None and base["away_odds"] is None:
            return None
        return base
    # Moneyline (h1, h2, q1..q4): outcomes named by team.
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        team_name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        if team_name is None or price is None:
            continue
        if home and team_name.casefold() == home.casefold():
            base["home_odds"] = price
        elif away and team_name.casefold() == away.casefold():
            base["away_odds"] = price
    if base["home_odds"] is None and base["away_odds"] is None:
        return None
    return base
