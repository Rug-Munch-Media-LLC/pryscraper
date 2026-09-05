"""ESPN scoreboard odds mappers for the sports odds engine.

Maps the ``odds`` block ESPN publishes on each competition (moneyline in
American format, spread and over/under lines where published) onto the
canonical odds record schema and the multi-book comparison dict. Pure
functions — no network — shared by the ESPN fallback fetchers in
:mod:`sports_data.odds`.

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

from datasets.sports_data.odds_common import (
    _MARKET_H2H,
    _MARKET_SPREADS,
    _MARKET_TOTALS,
    _american_to_decimal,
    _as_text,
    _canonical_book,
    _event_label,
    _nested,
    _to_float,
)


def _espn_competitors(
    comp: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract (home, away, home_score, away_score) from an ESPN competition."""
    home = away = home_score = away_score = None
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return home, away, home_score, away_score
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team")
        name = _as_text(team.get("displayName")) if isinstance(team, dict) else None
        if c.get("homeAway") == "home":
            home = name
            home_score = _as_text(c.get("score"))
        elif c.get("homeAway") == "away":
            away = name
            away_score = _as_text(c.get("score"))
    return home, away, home_score, away_score


def _espn_odds_to_records(
    comp: dict[str, Any],
    sport_slug: str,
    home: str | None,
    away: str | None,
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Map the ESPN ``odds`` block of one competition onto canonical records."""
    event = _event_label(home, away)
    if not event:
        return []
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list):
        return []
    wanted_markets = markets or [_MARKET_H2H]
    records: list[dict[str, Any]] = []
    for odd in odds_list:
        if not isinstance(odd, dict):
            continue
        provider = odd.get("provider")
        title = _as_text(provider.get("name")) if isinstance(provider, dict) else None
        if not title:
            continue
        book = _canonical_book(title)
        event_id = _as_text(comp.get("id"))
        base = {
            "sport": sport_slug,
            "event": event,
            "event_id": event_id,
            "book": book,
            "bookmaker": title,
            "home": home,
            "away": away,
            "last_update": None,
            "source": "espn",
        }
        for market in wanted_markets:
            if market == _MARKET_H2H:
                home_ml = _american_to_decimal(_nested(odd, "homeTeamOdds", "moneyLine"))
                away_ml = _american_to_decimal(_nested(odd, "awayTeamOdds", "moneyLine"))
                if home_ml is None and away_ml is None:
                    continue
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_H2H,
                        "home_odds": home_ml,
                        "away_odds": away_ml,
                        "draw_odds": None,
                        "spread": None,
                        "total": None,
                    }
                )
                records.append(record)
            elif market == _MARKET_SPREADS:
                spread = _to_float(odd.get("spread"))
                if spread is None:
                    continue
                home_so = _american_to_decimal(_nested(odd, "homeTeamOdds", "spreadOdds"))
                away_so = _american_to_decimal(_nested(odd, "awayTeamOdds", "spreadOdds"))
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_SPREADS,
                        "home_odds": home_so,
                        "away_odds": away_so,
                        "draw_odds": None,
                        "spread": spread,
                        "total": None,
                    }
                )
                records.append(record)
            elif market == _MARKET_TOTALS:
                total = _to_float(odd.get("overUnder"))
                if total is None:
                    continue
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_TOTALS,
                        "home_odds": None,
                        "away_odds": None,
                        "draw_odds": None,
                        "spread": None,
                        "total": total,
                    }
                )
                records.append(record)
    return records


def _espn_odds_to_comparison(
    comp: dict[str, Any],
    sport_slug: str,
    event_id: str,
    markets: list[str] | None = None,
    book: str | None = None,
) -> dict[str, Any]:
    """Build a multi-book comparison dict from one ESPN competition's odds."""
    home, away, _home_score, _away_score = _espn_competitors(comp)
    odds_list = comp.get("odds")
    bookmakers: list[dict[str, Any]] = []
    if isinstance(odds_list, list):
        for odd in odds_list:
            if not isinstance(odd, dict):
                continue
            provider = odd.get("provider")
            title = _as_text(provider.get("name")) if isinstance(provider, dict) else None
            if not title:
                continue
            book_slug = _canonical_book(title)
            if book is not None and book_slug != book:
                continue
            outcomes: list[dict[str, Any]] = []
            home_ml = _american_to_decimal(_nested(odd, "homeTeamOdds", "moneyLine"))
            away_ml = _american_to_decimal(_nested(odd, "awayTeamOdds", "moneyLine"))
            if home_ml is not None and home is not None:
                outcomes.append({"name": home, "price": home_ml})
            if away_ml is not None and away is not None:
                outcomes.append({"name": away, "price": away_ml})
            if outcomes:
                bookmakers.append(
                    {
                        "key": None,
                        "title": title,
                        "book": book_slug,
                        "markets": [{"key": _MARKET_H2H, "outcomes": outcomes}],
                    }
                )
    return {
        "event_id": event_id,
        "sport": sport_slug,
        "event": _event_label(home, away) or "",
        "commence_time": None,
        "bookmakers": bookmakers,
        "source": "espn",
    }
