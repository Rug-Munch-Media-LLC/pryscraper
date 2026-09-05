"""Parsers and modeled-line synthesis for alternate betting lines.

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

from datasets.sports_data.alt_lines_common import (
    _as_text,
    _canonical_book,
    _event_label,
    _round_half,
    _to_float,
)

# Spread ladder around the ESPN base (home-perspective deltas).
_ALT_SPREAD_STEPS = (0.0, 1.0, -1.0, 2.0, -2.0, 3.5, -3.5, 7.0, -7.0, 10.5, -10.5)
# Total ladder around the ESPN base.
_ALT_TOTAL_STEPS = (0.0, 3.5, -3.5, 7.0, -7.0, 10.5, -10.5, 14.0, -14.0)
# Modeled probability movement per point away from the base line.
_SPREAD_SLOPE = 0.03
_TOTAL_SLOPE = 0.02
_MARGIN = 0.045


def _map_alt_event(
    raw: dict[str, Any], sport_slug: str, wanted: set[str], book_slug: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API alternate-markets payload onto alt-line records."""
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
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            if market_key == "alternate_spreads" and "spread" in wanted:
                records.extend(
                    _parse_alt_spreads(outcomes, home, away, event, event_id, sport_slug, book)
                )
            elif market_key == "alternate_totals" and "total" in wanted:
                records.extend(_parse_alt_totals(outcomes, event, event_id, sport_slug, book))
    return records


def _parse_alt_spreads(
    outcomes: list[Any],
    home: str | None,
    away: str | None,
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> list[dict[str, Any]]:
    """Parse ``alternate_spreads`` outcomes (name=team, point, price)."""
    records: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        point = _to_float(outcome.get("point"))
        if name is None or price is None or point is None:
            continue
        if home and name.casefold() == home.casefold():
            records.append(
                {
                    "event": event,
                    "event_id": event_id,
                    "sport": sport_slug,
                    "market": "spread",
                    "line": point,
                    "home_odds": price,
                    "away_odds": None,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
        elif away and name.casefold() == away.casefold():
            records.append(
                {
                    "event": event,
                    "event_id": event_id,
                    "sport": sport_slug,
                    "market": "spread",
                    "line": -point,
                    "home_odds": None,
                    "away_odds": price,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
    # Merge home/away legs that share the same absolute line into one record.
    merged: dict[float, dict[str, Any]] = {}
    for record in records:
        line = float(record["line"])
        if line not in merged:
            merged[line] = record
        else:
            target = merged[line]
            if target.get("home_odds") is None and record.get("home_odds") is not None:
                target["home_odds"] = record["home_odds"]
            if target.get("away_odds") is None and record.get("away_odds") is not None:
                target["away_odds"] = record["away_odds"]
    return sorted(merged.values(), key=lambda r: float(r["line"]))


def _parse_alt_totals(
    outcomes: list[Any],
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> list[dict[str, Any]]:
    """Parse ``alternate_totals`` outcomes (Over/Under, point, price)."""
    by_point: dict[float, dict[str, Any]] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = str(outcome.get("name") or "").strip().lower()
        price = _to_float(outcome.get("price"))
        point = _to_float(outcome.get("point"))
        if name not in {"over", "under", "o", "u"} or price is None or point is None:
            continue
        side = "over" if name in {"over", "o"} else "under"
        entry = by_point.setdefault(
            point,
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "total",
                "line": point,
                "home_odds": None,
                "away_odds": None,
                "book": book,
                "source": "the_odds_api",
            },
        )
        if side == "over":
            entry["home_odds"] = price
        else:
            entry["away_odds"] = price
    return sorted(by_point.values(), key=lambda r: float(r["line"]))


# ── ESPN modeled fallback ───────────────────────────────────────────────
def _vigged_odds(prob: float, margin: float = _MARGIN) -> tuple[float, float]:
    """Convert a raw probability into vigged decimal odds for both sides."""
    p = min(max(prob, 0.05), 0.95)
    home = 1.0 / (p / (1.0 + margin))
    away = 1.0 / ((1.0 - p) / (1.0 + margin))
    return round(home, 2), round(away, 2)


def _modeled_spread_lines(
    event: str, event_id: str, sport_slug: str, base: float
) -> list[dict[str, Any]]:
    """Synthesize an alternate spread ladder around ESPN's base spread."""
    records: list[dict[str, Any]] = []
    seen: set[float] = set()
    for delta in _ALT_SPREAD_STEPS:
        line = _round_half(base + delta)
        if line in seen:
            continue
        seen.add(line)
        prob_home = 0.5 + delta * _SPREAD_SLOPE
        home_odds, away_odds = _vigged_odds(prob_home)
        records.append(
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "spread",
                "line": line,
                "home_odds": home_odds,
                "away_odds": away_odds,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records


def _modeled_total_lines(
    event: str, event_id: str, sport_slug: str, base: float
) -> list[dict[str, Any]]:
    """Synthesize an alternate total ladder around ESPN's base total."""
    records: list[dict[str, Any]] = []
    seen: set[float] = set()
    for delta in _ALT_TOTAL_STEPS:
        line = _round_half(base + delta)
        if line in seen:
            continue
        seen.add(line)
        prob_over = 0.5 - delta * _TOTAL_SLOPE
        over_odds, under_odds = _vigged_odds(prob_over)
        records.append(
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "total",
                "line": line,
                "home_odds": over_odds,
                "away_odds": under_odds,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records


def _espn_competitors(
    comp: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract (home, away) names from an ESPN competition."""
    home = away = None
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return home, away
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team")
        name = _as_text(team.get("displayName")) if isinstance(team, dict) else None
        if c.get("homeAway") == "home":
            home = name
        elif c.get("homeAway") == "away":
            away = name
    return home, away


def _espn_base_line(comp: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract the base (spread, total) from an ESPN competition's odds block."""
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list):
        return None, None
    spread: float | None = None
    total: float | None = None
    for odd in odds_list:
        if not isinstance(odd, dict):
            continue
        if spread is None:
            spread = _to_float(odd.get("spread"))
        if total is None:
            total = _to_float(odd.get("overUnder"))
        if spread is not None and total is not None:
            break
    return spread, total


__all__ = [
    "_espn_base_line",
    "_espn_competitors",
    "_map_alt_event",
    "_modeled_spread_lines",
    "_modeled_total_lines",
    "_parse_alt_spreads",
    "_parse_alt_totals",
    "_vigged_odds",
]
