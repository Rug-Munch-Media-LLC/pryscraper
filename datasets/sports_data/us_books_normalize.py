"""Canonical market keys + pure normalization helpers for US book feeds.

Extracted from :mod:`datasets.sports_data.us_books` — these are pure
functions/constants with no transport or I/O, shared by the per-book
parsers (:mod:`datasets.sports_data.us_books_parsers`) and the fetch core
(:mod:`datasets.sports_data.us_books`).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re
from typing import Any

# ── Canonical market keys (mirror sports_data.odds) ────────────────────
_MARKET_H2H = "h2h"
_MARKET_SPREADS = "spreads"
_MARKET_TOTALS = "totals"
_MARKETS = (_MARKET_H2H, _MARKET_SPREADS, _MARKET_TOTALS)


# ── Shared record / normalization helpers ───────────────────────────────
def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_team(name: Any) -> str:
    """Normalize a team name for fuzzy matching (lowercase alnum words)."""
    if name is None:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", str(name).lower()))


def _american_to_decimal(price: Any) -> float | None:
    """Convert American moneyline odds (e.g. -150, +125) to decimal odds."""
    value = _to_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return round(1 + value / 100, 2)
    return round(1 + 100 / abs(value), 2)


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional 'Away @ Home' event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _split_event_name(name: Any) -> tuple[str | None, str | None]:
    """Split an event name like 'Celtics @ Lakers' into (away, home).

    US books use the sportsbook convention 'Away @ Home'; 'vs'/'at'/' - '
    separators are accepted too. Returns ``(None, None)`` when unparseable.
    """
    if not name:
        return None, None
    # Separators must be surrounded by whitespace so "at" never matches
    # inside a team name like "Heats" (regex is case-insensitive).
    parts = re.split(
        r"\s+(?:@|vs\.?|at)\s+|\s+[-\u2013]\s+",
        str(name).strip(),
        maxsplit=1,
        flags=re.I,
    )
    if len(parts) < 2:
        return None, None
    away = _as_text(parts[0])
    home = _as_text(parts[1])
    if not away or not home:
        return None, None
    return away, home


def _record(
    *,
    sport: str,
    event: str,
    event_id: str | None,
    market: str,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    home_odds: float | None,
    away_odds: float | None,
    draw_odds: float | None = None,
    spread: float | None = None,
    total: float | None = None,
    last_update: str | None,
    source: str,
) -> dict[str, Any]:
    """Build one canonical odds record (same schema as sports_data.odds)."""
    return {
        "sport": sport,
        "event": event,
        "event_id": event_id,
        "market": market,
        "book": book,
        "bookmaker": bookmaker,
        "home": home,
        "away": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
        "spread": spread,
        "total": total,
        "last_update": last_update,
        "source": source,
    }


def _market_records(
    market: str,
    selections: list[dict[str, Any]],
    *,
    sport: str,
    event: str,
    event_id: str | None,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Map one normalized market block onto canonical odds records.

    ``selections`` is a list of ``{"name", "price" (decimal), "point"}``
    dicts (price/point may be None). Mirrors sports_data.odds._market_records
    so the output is byte-for-byte compatible with the shared schema.
    """
    if market == _MARKET_H2H:
        prices: dict[str, float] = {}
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            if name is not None and price is not None:
                prices.setdefault(name.lower(), price)
        home_price = prices.get(home.lower()) if home else None
        away_price = prices.get(away.lower()) if away else None
        draw_price = prices.get("draw") or prices.get("tie")
        if home_price is None and away_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event,
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
                source=f"us_{book}",
            )
        ]

    if market == _MARKET_SPREADS:
        home_price = away_price = None
        home_point = away_point = None
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            point = _to_float(sel.get("point"))
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
                event=event,
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
                source=f"us_{book}",
            )
        ]

    if market == _MARKET_TOTALS:
        over_price = under_price = None
        total: float | None = None
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            point = _to_float(sel.get("point"))
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
                event=event,
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
                source=f"us_{book}",
            )
        ]

    return []


# ── Selection / market block normalization ──────────────────────────────
def _selection_price(sel: dict[str, Any]) -> float | None:
    """Decimal odds from any of the common selection price shapes."""
    odds = sel.get("odds")
    if isinstance(odds, dict):
        dec = _to_float(odds.get("decimal"))
        if dec is not None:
            return round(dec, 2)
        am = _to_float(odds.get("american"))
        if am is not None:
            return _american_to_decimal(am)
    dec = _to_float(sel.get("price"))
    if dec is not None:
        return round(dec, 2)
    am = _to_float(sel.get("oddsAmerican"))
    if am is not None:
        return _american_to_decimal(am)
    dec = _to_float(sel.get("decimalOdds"))
    if dec is not None:
        return round(dec, 2)
    # FanDuel cache shape: fractional numerator/denominator (price = 1 + up/down).
    up = _to_float(sel.get("currentpriceup"))
    down = _to_float(sel.get("currentpricedown"))
    if up is not None and down and down != 0:
        return round(1 + up / down, 2)
    return None


def _selection_point(sel: dict[str, Any]) -> float | None:
    """Handicap / total line from a selection, in several known shapes."""
    for key in ("handicap", "point", "line", "spread", "total"):
        value = _to_float(sel.get(key))
        if value is not None:
            return value
    return None


def _point_from_label(name: str) -> float | None:
    """Pull a trailing number from a label like 'Over 220.5' or 'Lakers -5.5'."""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(name or ""))
    if match is None:
        return None
    return _to_float(match.group(0))


def _normalize_selection(sel: Any) -> dict[str, Any]:
    """Normalize one raw selection/outcome into ``{name, price, point}``."""
    if not isinstance(sel, dict):
        return {"name": None, "price": None, "point": None}
    name = _as_text(sel.get("label") or sel.get("name") or sel.get("participant"))
    point = _selection_point(sel)
    price = _selection_price(sel)
    if (
        point is None
        and name
        and (name.lower().startswith("over") or name.lower().startswith("under"))
    ):
        point = _point_from_label(name)
    return {"name": name, "price": price, "point": point}


def _selections_of(block: Any) -> list[dict[str, Any]]:
    """Collect selection dicts from a market block in several known shapes."""
    if not isinstance(block, dict):
        return []
    for key in ("selections", "outcomes", "betOfferRows"):
        values = block.get(key)
        if isinstance(values, list):
            return [_normalize_selection(v) for v in values if isinstance(v, dict)]
    # Flatten markets[0].outcomes (DraftKings nests outcomes under markets[]).
    markets = block.get("markets")
    if isinstance(markets, list) and markets:
        return _selections_of(markets[0] if isinstance(markets[0], dict) else {})
    outcomes = block.get("outcomes")
    if isinstance(outcomes, list):
        return [_normalize_selection(v) for v in outcomes if isinstance(v, dict)]
    return []


def _market_key(name: Any) -> str | None:
    """Map a raw market name to a canonical market key (h2h/spreads/totals)."""
    norm = _normalize_team(name)
    if not norm:
        return None
    if any(token in norm for token in ("moneyline", "h2h", "head head", "win")):
        return _MARKET_H2H
    if any(token in norm for token in ("spread", "handicap", "point spread")):
        return _MARKET_SPREADS
    if any(token in norm for token in ("total", "over under", "overunder")):
        return _MARKET_TOTALS
    return None


def _market_blocks(markets: Any) -> list[dict[str, Any]]:
    """Split a raw markets list into canonical blocks.

    Returns ``[{market, selections}]`` where ``selections`` are normalized
    ``{name, price, point}`` dicts. Blocks with no usable selections are
    dropped.
    """
    blocks: list[dict[str, Any]] = []
    if not isinstance(markets, list):
        return blocks
    for market in markets:
        if not isinstance(market, dict):
            continue
        key = _market_key(market.get("name") or market.get("marketType"))
        if key is None:
            continue
        selections = _selections_of(market)
        if not selections:
            continue
        blocks.append({"market": key, "selections": selections})
    return blocks
