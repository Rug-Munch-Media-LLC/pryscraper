"""JSON-tree market extraction strategies."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.books_markets.helpers import _event_teams, _iter_dicts, _outcome_groups
from datasets.sports_data.books_markets.records import _records_for_outcome_group
from datasets.sports_data.books_normalize import _as_text, _decimal_odds, _make_record


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
