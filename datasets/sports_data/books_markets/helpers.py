"""Low-level market, team, and outcome helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.books_normalize import _as_text, _decimal_odds

_DRAW_NAMES = {"draw", "tie", "x", "empate", "nul"}


def _iter_dicts(node: Any):
    """Yield every dict nested in ``node`` (parent before children)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


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
