"""Shared constants and helpers for period (half/quarter) betting markets.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
from typing import Any

import httpx

from pry.engine.retry import RetryConfig

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import (
        _SPORTS,
        _bookmaker_params,
        _canonical_book,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _bookmaker_params = None  # type: ignore[assignment]
    _canonical_book = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"

_API_KEY_ENV = "PRY_ODDS_API_KEY"
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}
_ODDS_API_REGIONS = "us"

# Period markets per canonical sport key. Kept to what books actually price;
# each market counts against the Odds API free-tier quota.
_PERIOD_MARKETS: dict[str, tuple[str, ...]] = {
    "basketball_nba": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_spreads",
        "q2_spreads",
        "q3_spreads",
        "q4_spreads",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "basketball_ncaab": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "basketball_wnba": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_nfl": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_ncaaf": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_cfl": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
    ),
    "soccer_epl": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_spain_la_liga": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_germany_bundesliga": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_italy_serie_a": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_uefa_champions_league": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_usa_mls": ("h1", "h2", "h1_totals", "h2_totals"),
}

# Raw market key -> normalized period label.
_PERIOD_LABELS: dict[str, str] = {
    "h1": "first_half",
    "h2": "second_half",
    "q1": "q1",
    "q2": "q2",
    "q3": "q3",
    "q4": "q4",
}


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


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


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional "Away @ Home" event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _resolve_event(event_id: str) -> tuple[list[str], str]:
    """Split a (possibly sport-prefixed) event id into (sport slugs, id)."""
    raw = str(event_id or "").strip()
    prefix, _, rest = raw.partition(":")
    if rest:
        if _resolve_sports is not None:
            return _resolve_sports(prefix), rest
        return [], rest
    if _resolve_sports is not None:
        return _resolve_sports("all"), raw
    return [], raw


def _canonical_key(slug: str) -> str:
    """Map a resolved slug (alias or canonical) to the Odds API sport key."""
    try:
        return _SPORTS[slug][0]
    except (KeyError, TypeError):
        return slug


def _period_markets_for(slug: str) -> list[str]:
    """Return the period market keys available for a sport slug."""
    return list(_PERIOD_MARKETS.get(_canonical_key(slug), []))


def _period_label(market_key: str) -> str | None:
    """Map a raw market key (h1, h2, q1, h1_totals, ...) to a period label."""
    base = market_key.split("_", 1)[0]
    return _PERIOD_LABELS.get(base)
