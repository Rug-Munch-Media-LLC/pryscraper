"""Shared registry + pure helpers for the sports odds engine.

Static sports/books metadata lives as plain JSON (data, not code) under
``data/odds.json``; this module loads it at import time and exposes the
canonical registries plus the small pure helpers every odds submodule
shares (coercion, book normalization, market normalization, record
building). No network, no I/O beyond the JSON load.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# ── Data-driven registry loader ─────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Markets ────────────────────────────────────────────────────────────
_MARKET_H2H = "h2h"
_MARKET_SPREADS = "spreads"
_MARKET_TOTALS = "totals"
_MARKET_OUTRIGHTS = "outrights"
_MARKETS_ALL: tuple[str, ...] = (
    _MARKET_H2H,
    _MARKET_SPREADS,
    _MARKET_TOTALS,
    _MARKET_OUTRIGHTS,
)

# Accept common aliases (moneyline, spread, over/under, futures...).
_MARKET_ALIASES: dict[str, str] = {
    "h2h": _MARKET_H2H,
    "ml": _MARKET_H2H,
    "moneyline": _MARKET_H2H,
    "spread": _MARKET_SPREADS,
    "spreads": _MARKET_SPREADS,
    "pointspread": _MARKET_SPREADS,
    "total": _MARKET_TOTALS,
    "totals": _MARKET_TOTALS,
    "overunder": _MARKET_TOTALS,
    "ou": _MARKET_TOTALS,
    "outrights": _MARKET_OUTRIGHTS,
    "futures": _MARKET_OUTRIGHTS,
    "winner": _MARKET_OUTRIGHTS,
    "championship": _MARKET_OUTRIGHTS,
}

# ── Sports ─────────────────────────────────────────────────────────────
# Canonical sport key (the Odds API key) -> ESPN (sport, league) fallback.
# ``None`` ESPN means The Odds API is the only source for that sport.
# Data-driven (JSON).
_ODDS_DATA: dict[str, Any] = _load_json("odds.json")
_CANONICAL_SPORTS: dict[str, tuple[str, str] | None] = {
    k: (v[0], v[1]) if v is not None else None for k, v in _ODDS_DATA["_CANONICAL_SPORTS"].items()
}

# Legacy short aliases -> canonical key (backward compatibility).
_SPORT_ALIASES: dict[str, str] = _ODDS_DATA["_SPORT_ALIASES"]


def _build_sports_table() -> dict[str, tuple[str, tuple[str, str] | None]]:
    """Build the lookup table: alias/canonical key -> (odds key, ESPN tuple)."""
    table: dict[str, tuple[str, tuple[str, str] | None]] = {}
    for key, espn in _CANONICAL_SPORTS.items():
        table[key] = (key, espn)
    for alias, canonical in _SPORT_ALIASES.items():
        table[alias] = table[canonical]
    return table


_SPORTS: dict[str, tuple[str, tuple[str, str] | None]] = _build_sports_table()

# The Odds API free tier is quota-bound (500 req/month); "all" never queries
# the full sport list. These are the sports betting bots care about most.
_DEFAULT_SPORTS: tuple[str, ...] = tuple(_ODDS_DATA["_DEFAULT_SPORTS"])

# ── Books ──────────────────────────────────────────────────────────────
# Canonical book slug -> the upstream identifiers that identify it.
# The values are The Odds API ``bookmakers`` keys (valid for the upstream
# request) — display titles live in ``_BOOK_TITLES`` below (normalization
# only, never sent upstream). Data-driven (JSON).
_BOOKS: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in _ODDS_DATA["_BOOKS"].items()}

# Display titles (ESPN provider names etc.) -> canonical slug. Used for
# normalization only — never sent upstream.
_BOOK_TITLES: dict[str, str] = _ODDS_DATA["_BOOK_TITLES"]

# ── Endpoints ──────────────────────────────────────────────────────────
_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

_API_KEY_ENV = "PRY_ODDS_API_KEY"

# Request/limit constants shared by the odds entry points.
_MAX_LIMIT = 100
_ODDS_API_REGIONS = "us"

# Canonical source names understood by the ``sources`` parameter.
_SOURCE_NAMES = ("the_odds_api", "espn", "oddsportal", "bovada", "betonline", "books")


def _parse_sources_param(sources: str | None) -> set[str] | None:
    """Normalize a ``sources`` param into the set of source names to query.

    ``None`` / ``""`` -> ``None`` (legacy behavior: The Odds API when a key
    is configured, else ESPN). ``"all"`` / ``"*"`` -> every source name
    (including ``"books"``, the 112-book direct scrapers). Unknown names
    are ignored (never raises); if nothing valid remains the result is
    ``None`` (legacy behavior).
    """
    if sources is None:
        return None
    raw = str(sources).strip().lower()
    if not raw or raw in {"all", "*"}:
        return set(_SOURCE_NAMES)
    names = {part.strip() for part in re.split(r"[,\s|]+", raw) if part.strip()}
    valid = names & set(_SOURCE_NAMES)
    return valid or None


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _resolve_sports(sport: str) -> list[str]:
    """Map a ``sport`` parameter to the list of sports to query.

    ``""`` / ``"all"`` → the default sports; a known canonical key or short
    alias (e.g. ``basketball_nba`` or ``nba``) → that one sport; anything
    unknown → ``[]`` (callers treat this as "invalid sport, return empty").
    """
    raw = str(sport or "").strip().lower()
    if raw in {"", "all"}:
        return list(_DEFAULT_SPORTS)
    if raw in _SPORTS:
        return [raw]
    return []


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


def _nested(mapping: Any, *keys: str) -> Any:
    """Dive into nested dicts, returning None if any level is missing."""
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _american_to_decimal(price: Any) -> float | None:
    """Convert American moneyline odds (e.g. -150, +125) to decimal odds."""
    value = _to_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return round(1 + value / 100, 2)
    return round(1 + 100 / abs(value), 2)


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional "Away @ Home" event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _canonical_book(value: str | None) -> str:
    """Normalize a bookmaker key/title to a canonical book slug."""
    if not value:
        return "unknown"
    norm = "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    for slug, keys in _BOOKS.items():
        for key in keys:
            if "".join(ch for ch in key.lower() if ch.isalnum()) == norm:
                return slug
    for title, slug in _BOOK_TITLES.items():
        if "".join(ch for ch in title.lower() if ch.isalnum()) == norm:
            return slug
    return norm or "unknown"


def _bookmaker_params(book_key: str) -> str | None:
    """Map a canonical book slug to the The Odds API ``bookmakers`` value."""
    keys = _BOOKS.get(book_key)
    if not keys:
        return None
    return ",".join(keys)


def _normalize_markets(market: str) -> list[str]:
    """Normalize a ``market`` parameter into the canonical markets to fetch.

    Accepts comma or pipe separated values plus aliases (``moneyline``,
    ``spread``, ``overunder``, ``futures``...). ``"all"`` / ``"*"`` requests
    every market; anything unparseable falls back to ``h2h``.
    """
    raw = str(market or "").strip().lower().replace("|", ",")
    if raw in {"all", "*"}:
        return list(_MARKETS_ALL)
    if not raw:
        return [_MARKET_H2H]
    markets: list[str] = []
    for part in raw.split(","):
        part = part.strip().lower()
        canonical = _MARKET_ALIASES.get(part)
        if canonical is not None and canonical not in markets:
            markets.append(canonical)
    return markets or [_MARKET_H2H]


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
    """Build one canonical odds record (the shared schema across sources)."""
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
