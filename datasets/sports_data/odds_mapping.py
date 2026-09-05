"""The Odds API response mappers for the sports odds engine.

Maps raw The Odds API event payloads onto the canonical odds record schema
(:func:`sports_data.odds_common._record`). Pure functions — no network, no
I/O — so they are trivially testable and safe to reuse from any source.

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
    _MARKET_ALIASES,
    _MARKET_H2H,
    _MARKET_OUTRIGHTS,
    _MARKET_SPREADS,
    _MARKET_TOTALS,
    _as_text,
    _canonical_book,
    _event_label,
    _record,
    _to_float,
)


def _outcome_prices(outcomes: Any) -> dict[str, float]:
    """Map normalized outcome name -> decimal price for one market."""
    prices: dict[str, float] = {}
    if not isinstance(outcomes, list):
        return prices
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        if name is not None and price is not None:
            prices.setdefault(name.lower(), price)
    return prices


def _market_records(
    market_key: str,
    outcomes: Any,
    *,
    sport: str,
    event: str | None,
    event_id: str | None,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Map one (bookmaker, market) block onto canonical odds records."""
    market = _MARKET_ALIASES.get(str(market_key or "").strip().lower(), _MARKET_H2H)

    if market == _MARKET_H2H:
        prices = _outcome_prices(outcomes)
        home_price = prices.get(home.lower()) if home else None
        away_price = prices.get(away.lower()) if away else None
        draw_price = prices.get("draw") or prices.get("tie")
        if home_price is None and away_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_H2H,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                draw_odds=draw_price,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_SPREADS:
        home_price = away_price = None
        home_point = away_point = None
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name is None or price is None:
                continue
            if home and name.lower() == home.lower():
                home_price, home_point = price, point
            elif away and name.lower() == away.lower():
                away_price, away_point = price, point
        if home_price is None and away_price is None:
            return []
        spread = home_point
        if spread is None and away_point is not None:
            spread = -away_point
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_SPREADS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                spread=spread,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_TOTALS:
        over_price = under_price = None
        total: float | None = None
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name is None or price is None:
                continue
            if name.lower() in {"over", "o"}:
                over_price, total = price, point
            elif name.lower() in {"under", "u"}:
                under_price, total = price, point
        if over_price is None and under_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_TOTALS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=over_price,
                away_odds=under_price,
                total=total,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_OUTRIGHTS:
        contenders: list[tuple[str, float]] = []
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            if name is not None and price is not None:
                contenders.append((name, price))
        records: list[dict[str, Any]] = []
        for name, price in contenders:
            records.append(
                _record(
                    sport=sport,
                    event=event or name,
                    event_id=event_id,
                    market=_MARKET_OUTRIGHTS,
                    book=book,
                    bookmaker=bookmaker,
                    home=name,
                    away=None,
                    home_odds=price,
                    away_odds=None,
                    last_update=last_update,
                    source="the_odds_api",
                )
            )
        return records

    return []


def _map_odds_event(
    raw: dict[str, Any],
    sport_key: str,
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Map one The Odds API event object onto canonical odds records.

    ``markets`` optionally restricts which markets are emitted (upstream
    usually filters server-side; this keeps the mapper defensive).
    """
    wanted = markets or [_MARKET_H2H]
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away)
    event_id = _as_text(raw.get("id"))
    commence = _as_text(raw.get("commence_time"))
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
        book = _canonical_book(_as_text(bk.get("key")) or title)
        last_update = _as_text(bk.get("last_update")) or commence
        markets_list = bk.get("markets")
        if not isinstance(markets_list, list):
            continue
        for mkt in markets_list:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or _MARKET_H2H
            canonical = _MARKET_ALIASES.get(market_key, _MARKET_H2H)
            if canonical not in wanted:
                continue
            records.extend(
                _market_records(
                    market_key,
                    mkt.get("outcomes"),
                    sport=sport_key,
                    event=event,
                    event_id=event_id,
                    book=book,
                    bookmaker=title,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _map_event_comparison(
    raw: dict[str, Any],
    sport_slug: str,
    markets: list[str] | None = None,
    book: str | None = None,
) -> dict[str, Any]:
    """Map a single-event Odds API payload onto the comparison dict."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away) or ""
    wanted_markets = markets or [_MARKET_H2H]
    bookmakers: list[dict[str, Any]] = []
    raw_bookmakers = raw.get("bookmakers")
    if isinstance(raw_bookmakers, list):
        for bk in raw_bookmakers:
            if not isinstance(bk, dict):
                continue
            bk_key = _as_text(bk.get("key"))
            title = _as_text(bk.get("title")) or bk_key
            if not title:
                continue
            book_slug = _canonical_book(bk_key or title)
            if book is not None and book_slug != book:
                continue
            markets_out: list[dict[str, Any]] = []
            raw_markets = bk.get("markets")
            if isinstance(raw_markets, list):
                for mkt in raw_markets:
                    if not isinstance(mkt, dict):
                        continue
                    mkt_key = _as_text(mkt.get("key")) or _MARKET_H2H
                    canonical_mkt = _MARKET_ALIASES.get(mkt_key, _MARKET_H2H)
                    if canonical_mkt not in wanted_markets:
                        continue
                    outcomes: list[dict[str, Any]] = []
                    raw_outcomes = mkt.get("outcomes")
                    if isinstance(raw_outcomes, list):
                        for outcome in raw_outcomes:
                            if not isinstance(outcome, dict):
                                continue
                            price = _to_float(outcome.get("price"))
                            name = _as_text(outcome.get("name"))
                            if name is None or price is None:
                                continue
                            entry: dict[str, Any] = {"name": name, "price": price}
                            point = _to_float(outcome.get("point"))
                            if point is not None:
                                entry["point"] = point
                            outcomes.append(entry)
                    if outcomes:
                        markets_out.append({"key": mkt_key, "outcomes": outcomes})
            bookmakers.append(
                {
                    "key": bk_key,
                    "title": title,
                    "book": book_slug,
                    "markets": markets_out,
                }
            )
    return {
        "event_id": _as_text(raw.get("id")),
        "sport": sport_slug,
        "event": event,
        "commence_time": _as_text(raw.get("commence_time")),
        "bookmakers": bookmakers,
        "source": "the_odds_api",
    }
