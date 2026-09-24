"""Market-specific normalized odds record builders."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.books_markets.helpers import (
    _is_draw_name,
    _normalize_market_key,
    _outcome_price,
    _price_for,
)
from datasets.sports_data.books_normalize import _as_text, _make_record, _to_float


def _h2h_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if home and away:
        home_odds = _price_for(prices, home)
        away_odds = _price_for(prices, away)
        if home_odds is None and away_odds is None and len(prices) >= 2:
            home_odds, away_odds = prices[0]["price"], prices[1]["price"]
        draw_odds: float | None = None
        if len(prices) >= 3:
            for entry in prices[2:]:
                if _is_draw_name(entry.get("name")):
                    draw_odds = entry["price"]
                    break
            if draw_odds is None:
                for entry in prices:
                    name = (entry.get("name") or "").lower()
                    if name and name not in (home.lower(), away.lower()):
                        draw_odds = entry["price"]
                        break
        if home_odds is None and away_odds is None:
            return []
        return [
            _make_record(
                book,
                sport,
                event or f"{home} @ {away}",
                "h2h",
                home,
                away,
                home_odds,
                away_odds,
                draw_odds,
                None,
                None,
            )
        ]
    names = [entry["name"] for entry in prices if entry.get("name")]
    if len(prices) >= 2 and len(names) >= 2:
        home = names[0]
        away = names[1]
        draw_odds = prices[2]["price"] if len(prices) > 2 and _is_draw_name(names[2]) else None
        return [
            _make_record(
                book,
                sport,
                event or f"{home} @ {away}",
                "h2h",
                home,
                away,
                prices[0]["price"],
                prices[1]["price"],
                draw_odds,
                None,
                None,
            )
        ]
    return []


def _spread_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lined = [entry for entry in prices if entry.get("line") is not None]
    if len(lined) < 2:
        return []
    first, second = lined[0], lined[1]
    home = home or first.get("name")
    away = away or second.get("name")
    if not home or not away:
        return []
    return [
        _make_record(
            book,
            sport,
            event or f"{home} @ {away}",
            "spreads",
            home,
            away,
            first["price"],
            second["price"],
            None,
            first["line"],
            None,
        )
    ]


def _total_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lined = [entry for entry in prices if entry.get("line") is not None]
    if not lined:
        return []
    over = next(
        (entry for entry in lined if entry.get("name") and "over" in entry["name"].lower()),
        None,
    )
    under = next(
        (entry for entry in lined if entry.get("name") and "under" in entry["name"].lower()),
        None,
    )
    if over is None and under is None:
        over, under = lined[0], lined[1] if len(lined) > 1 else lined[0]
    total = (over or under or lined[0]).get("line")
    home = home or (over.get("name") if over else None) or "Over"
    away = away or (under.get("name") if under else None) or "Under"
    return [
        _make_record(
            book,
            sport,
            event or f"{home} @ {away}",
            "totals",
            home,
            away,
            over["price"] if over else None,
            under["price"] if under else None,
            None,
            None,
            total,
        )
    ]


def _records_for_outcome_group(
    book: dict[str, Any],
    context: dict[str, Any],
    market_key: str | None,
    outcomes: list[Any],
    sport: str,
    market: str,
    event: str | None,
    home: str | None,
    away: str | None,
) -> list[dict[str, Any]]:
    normalized = _normalize_market_key(market_key)
    if market != "all" and normalized is not None and normalized != market:
        return []
    target = normalized or market
    prices: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        price = _outcome_price(outcome)
        if price is None:
            continue
        line_value = outcome.get("line")
        if line_value is None:
            line_value = outcome.get("point")
        prices.append(
            {
                "name": _as_text(outcome.get("name")),
                "price": price,
                "line": _to_float(line_value),
            }
        )
    if not prices:
        return []
    if target == "spreads":
        return _spread_record(book, sport, event, home, away, prices)
    if target == "totals":
        return _total_record(book, sport, event, home, away, prices)
    return _h2h_record(book, sport, event, home, away, prices)
