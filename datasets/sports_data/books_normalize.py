"""Odds normalization helpers for the sportsbook registry scrapers.

Pure functions: text coercion, decimal-odds conversion (American /
fractional / decimal) and the canonical odds-record builder shared by
every extraction path in :mod:`datasets.sports_data.books`.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _american_to_decimal(american: float) -> float:
    if american > 0:
        return round(american / 100 + 1, 2)
    return round(100 / abs(american) + 1, 2)


def _decimal_odds(value: Any) -> float | None:
    """Coerce any price format to decimal odds.

    Accepts American (``-110``, ``+120``, ``100``), fractional (``5/2``)
    and decimal (``1.91``) forms. Returns ``None`` for unparseable input.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if abs(number) >= 100 and number == int(number):
            return _american_to_decimal(number)
        return round(number, 2) if number > 1.0 else None
    text = str(value).strip()
    if not text:
        return None
    if "/" in text:
        try:
            numerator, denominator = text.split("/", 1)
            fraction = float(numerator) / float(denominator)
            return round(fraction + 1.0, 2)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        number = float(text)
    except ValueError:
        return None
    if text.startswith(("+", "-")):
        return _american_to_decimal(number)
    if text.isdigit() and number >= 100:
        return _american_to_decimal(number)
    return round(number, 2) if number > 1.0 else None


def _make_record(
    book: dict[str, Any],
    sport: str,
    event: str,
    market: str,
    home: str | None,
    away: str | None,
    home_odds: float | None,
    away_odds: float | None,
    draw_odds: float | None = None,
    spread: float | None = None,
    total: float | None = None,
) -> dict[str, Any]:
    """Build one canonical odds record (task schema)."""
    return {
        "sport": sport,
        "event": event,
        "market": market,
        "book": book["name"],
        "book_id": book["id"],
        "home": home,
        "away": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
        "spread": spread,
        "total": total,
        "last_update": _now_iso(),
        "source": f"books:{book['id']}",
    }
