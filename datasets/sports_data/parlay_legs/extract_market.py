"""Market and team-name extraction for parlay legs."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.parlay_legs.fair import _fair_probability
from datasets.sports_data.parlay_math import _as_text, _to_float


def _comparison_team_names(comparison: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort (home, away) names from an event comparison dict.

    ``get_event_odds`` does not expose team names directly, so this parses
    the conventional ``"Away @ Home"`` event label as a fallback and finally
    falls back to outcome names from the h2h market.
    """
    if not isinstance(comparison, dict):
        return None, None
    event = _as_text(comparison.get("event"))
    if event and "@" in event:
        away, _, home = event.partition("@")
        away_name = away.strip() or None
        home_name = home.strip() or None
        if away_name and home_name:
            return home_name, away_name
    bookmakers = comparison.get("bookmakers")
    if isinstance(bookmakers, list):
        for bk in bookmakers:
            if not isinstance(bk, dict):
                continue
            for mkt in bk.get("markets") or []:
                if not isinstance(mkt, dict):
                    continue
                if str(mkt.get("key") or "").lower() != "h2h":
                    continue
                names = [
                    str(outcome.get("name")).strip()
                    for outcome in mkt.get("outcomes") or []
                    if isinstance(outcome, dict) and outcome.get("name")
                ]
                if len(names) >= 2:
                    return names[0], names[1]
    return None, None


def _market_legs_from_outcomes(
    market_key: str,
    outcomes: list[dict[str, Any]],
    home_name: str | None,
    away_name: str | None,
    book: str,
) -> list[dict[str, Any]]:
    """Build normalized legs from one bookmaker's market outcomes."""
    if not isinstance(outcomes, list):
        return []
    outcomes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    key = str(market_key or "").lower()
    legs: list[dict[str, Any]] = []
    # Only entries with a non-None price are appended (guarded at build time),
    # so the price slot is a plain float.
    priced: list[tuple[str, float, float | None]] = []
    if key == "h2h":
        for outcome in outcomes:
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            if not name or price is None:
                continue
            priced.append((name, price, None))
    elif key in {"spreads", "spread"}:
        for outcome in outcomes:
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if not name or price is None:
                continue
            priced.append((name, price, point))
    elif key in {"totals", "total"}:
        for outcome in outcomes:
            name = str(outcome.get("name") or "").strip().lower()
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name not in {"over", "under", "o", "u"} or price is None:
                continue
            side = "over" if name in {"over", "o"} else "under"
            priced.append((side, price, point))
    else:
        return legs
    if key == "h2h":
        side_odds = [odds for _name, odds, _pt in priced[:2] if odds is not None]
        for name, price, _point in priced:
            fair = _fair_probability(
                float(price),
                side_odds[0] if side_odds else None,
                side_odds[1] if len(side_odds) > 1 else None,
            )
            legs.append(
                {
                    "market": "h2h",
                    "side": name,
                    "team": name,
                    "line": None,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": name,
                    "book": book,
                }
            )
    elif key in {"spreads", "spread"}:
        side_odds = [odds for _name, odds, _pt in priced[:2] if odds is not None]
        for name, price, point in priced:
            fair = _fair_probability(
                float(price),
                side_odds[0] if side_odds else None,
                side_odds[1] if len(side_odds) > 1 else None,
            )
            side = name
            if home_name and away_name:
                if name.casefold() == home_name.casefold():
                    side = "home"
                elif name.casefold() == away_name.casefold():
                    side = "away"
            legs.append(
                {
                    "market": "spread",
                    "side": side,
                    "team": name,
                    "line": point,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": f"{name} {point:+.1f}" if point is not None else name,
                    "book": book,
                }
            )
    elif key in {"totals", "total"}:
        over_odds = next((o for s, o, _p in priced if s == "over"), None)
        under_odds = next((o for s, o, _p in priced if s == "under"), None)
        total = next((p for _s, _o, p in priced if p is not None), None)
        for side, price, _point in priced:
            fair = _fair_probability(float(price), over_odds, under_odds)
            side_name = "Over" if side == "over" else "Under"
            legs.append(
                {
                    "market": "total",
                    "side": side,
                    "team": None,
                    "line": total,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": f"{side_name} {total}" if total is not None else side_name,
                    "book": book,
                }
            )
    return legs
