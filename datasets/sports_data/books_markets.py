"""Generic odds extraction from JSON trees (per-book market records).

Walks arbitrary JSON trees (internal API feeds, ``__NEXT_DATA__``,
``__NUXT__``, ``__INITIAL_STATE__``, ``_dida_config_``, JSON-LD) and
extracts normalized h2h / spreads / totals records via several detection
strategies: The Odds API style ``outcomes``, nested ``markets`` lists,
Bovada's ``displayGroups`` nesting, moneyline pairs and 1/X/2 three-way
odds.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.books_normalize import (
    _as_text,
    _decimal_odds,
    _make_record,
    _to_float,
)


def _iter_dicts(node: Any):
    """Yield every dict nested in ``node`` (parent before children)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


_DRAW_NAMES = {"draw", "tie", "x", "empate", "nul"}


def _is_draw_name(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() in _DRAW_NAMES


def _market_key(d: dict[str, Any]) -> str | None:
    for key in ("key", "type", "marketType", "market", "label"):
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_market_key(key: str | None) -> str | None:
    if not key:
        return None
    normalized = key.strip().lower()
    if normalized in (
        "h2h",
        "moneyline",
        "ml",
        "win",
        "1x2",
        "matchwinner",
        "match_winner",
        "h2h_3way",
    ):
        return "h2h"
    if normalized in ("spread", "spreads", "pointspread", "handicap", "spread_3way"):
        return "spreads"
    if normalized in ("total", "totals", "overunder", "ou", "over_under", "totalpoints"):
        return "totals"
    return None


def _event_teams(d: dict[str, Any]) -> tuple[str | None, str | None]:
    """Home/away team names from team keys or a Bovada-style competitors list."""
    for home_key, away_key in (
        ("home", "away"),
        ("homeTeam", "awayTeam"),
        ("home_team", "away_team"),
        ("team1", "team2"),
    ):
        home = _as_text(d.get(home_key))
        away = _as_text(d.get(away_key))
        if home and away:
            return home, away
    competitors = d.get("competitors")
    if isinstance(competitors, list):
        home_name: str | None = None
        away_name: str | None = None
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            name = _as_text(competitor.get("name"))
            if not name:
                continue
            if competitor.get("home") is True:
                home_name = name
            elif away_name is None:
                away_name = name
        if home_name and away_name:
            return home_name, away_name
    return None, None


def _outcome_groups(d: dict[str, Any]):
    """Yield ``(market_key, outcomes)`` pairs found in a dict (direct or nested).

    Handles The Odds API style (``outcomes``), nested ``markets`` lists and
    Bovada's ``displayGroups`` nesting.
    """
    outcomes = d.get("outcomes")
    if isinstance(outcomes, list):
        yield _market_key(d), outcomes
    markets = d.get("markets")
    if isinstance(markets, list):
        for market in markets:
            if isinstance(market, dict) and isinstance(market.get("outcomes"), list):
                yield _market_key(market), market["outcomes"]
    groups = d.get("displayGroups")
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict):
                yield from _outcome_groups(group)


def _outcome_price(outcome: dict[str, Any]) -> float | None:
    """Decimal price of one outcome dict (handles nested ``price`` objects)."""
    raw = outcome.get("price")
    if isinstance(raw, dict):
        for key in ("american", "decimal", "odds", "value"):
            if raw.get(key) is not None:
                return _decimal_odds(raw[key])
        return None
    if raw is not None:
        return _decimal_odds(raw)
    for key in ("american", "decimal", "odds", "value", "priceAmerican", "priceDecimal"):
        value = outcome.get(key)
        if value is not None:
            return _decimal_odds(value)
    return None


def _price_for(prices: list[dict[str, Any]], team: str | None) -> float | None:
    """Match an outcome price by team name (fuzzy, case-insensitive)."""
    if not team:
        return None
    needle = team.lower()
    for entry in prices:
        name = (entry.get("name") or "").lower()
        if name and (name == needle or name in needle or needle in name):
            return entry.get("price")
    return None


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


def _pair_odds(d: dict[str, Any]) -> tuple[float | None, float | None] | None:
    """Home/away odds pair embedded in one dict (moneyline style)."""
    for home_key, away_key in (
        ("home_odds", "away_odds"),
        ("homeOdds", "awayOdds"),
        ("moneyline_home", "moneyline_away"),
        ("home_moneyline", "away_moneyline"),
        ("home_price", "away_price"),
        ("price1", "price2"),
        ("odds1", "odds2"),
        ("home_ml", "away_ml"),
    ):
        home_value = d.get(home_key)
        away_value = d.get(away_key)
        if home_value is not None or away_value is not None:
            return _decimal_odds(home_value), _decimal_odds(away_value)
    return None


def _three_way_odds(d: dict[str, Any]) -> tuple[float | None, float | None, float | None] | None:
    """1/X/2 three-way odds (draw included) when the dict carries an ``X`` key."""
    if "X" not in d and "x" not in d:
        return None
    home = d.get("1")
    away = d.get("2")
    draw = d.get("X", d.get("x"))
    if home is None and away is None and draw is None:
        return None
    return _decimal_odds(home), _decimal_odds(away), _decimal_odds(draw)


def _records_from_dict(
    book: dict[str, Any],
    d: dict[str, Any],
    sport: str,
    market: str,
) -> list[dict[str, Any]]:
    """Extract odds records from one dict via every detection strategy."""
    records: list[dict[str, Any]] = []
    home, away = _event_teams(d)
    event: str | None
    if home and away:
        event = f"{home} @ {away}"
    else:
        event = (
            _as_text(d.get("event"))
            or _as_text(d.get("name"))
            or _as_text(d.get("description"))
            or _as_text(d.get("eventName"))
        )
    for market_key, outcomes in _outcome_groups(d):
        records.extend(
            _records_for_outcome_group(
                book, d, market_key, outcomes, sport, market, event, home, away
            )
        )
    if market in ("h2h", "all") and home and away:
        three_way = _three_way_odds(d)
        if three_way is not None:
            home_odds, away_odds, draw_odds = three_way
            if home_odds is not None or away_odds is not None:
                records.append(
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
                )
        else:
            pair = _pair_odds(d)
            if pair is not None and (pair[0] is not None or pair[1] is not None):
                records.append(
                    _make_record(
                        book,
                        sport,
                        event or f"{home} @ {away}",
                        "h2h",
                        home,
                        away,
                        pair[0],
                        pair[1],
                        None,
                        None,
                        None,
                    )
                )
    return records


def _walk_json(
    data: Any,
    book: dict[str, Any],
    sport: str,
    market: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Walk a JSON tree and collect odds records (capped at ``limit``)."""
    records: list[dict[str, Any]] = []
    for node in _iter_dicts(data):
        records.extend(_records_from_dict(book, node, sport, market))
        if len(records) >= limit:
            return records[:limit]
    return records
