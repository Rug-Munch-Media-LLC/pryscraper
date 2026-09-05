"""Shared constants and helpers for alternate-line fetching.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.retry import RetryConfig, async_retry

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import (
        _SPORTS,
        _american_to_decimal,
        _bookmaker_params,
        _canonical_book,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _american_to_decimal = None  # type: ignore[assignment]
    _bookmaker_params = None  # type: ignore[assignment]
    _canonical_book = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

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


def _round_half(value: float) -> float:
    """Round to the nearest 0.5 (standard line step)."""
    return round(value * 2) / 2


def _normalize_markets(market: str) -> set[str]:
    """Normalize the ``market`` param into {'spread'} / {'total'} / both."""
    raw = str(market or "").strip().lower().replace("|", ",")
    if raw in {"", "all", "both", "alternate"}:
        return {"spread", "total"}
    wanted: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if part in {"spread", "spreads", "alternate_spreads"}:
            wanted.add("spread")
        elif part in {"total", "totals", "alternate_totals"}:
            wanted.add("total")
    return wanted


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


def _book_api_param(book: str) -> str | None:
    """Map the ``book`` param to The Odds API ``bookmakers`` value (None=all)."""
    raw = str(book or "").strip().lower()
    if raw in {"", "all"}:
        return None
    if _canonical_book is None or _bookmaker_params is None:
        return None
    slug = _canonical_book(raw)
    if slug in {"", "unknown"}:
        return None
    return _bookmaker_params(slug)


# ── Transport ───────────────────────────────────────────────────────────
async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None``."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports alt-lines payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


__all__ = [
    "_API_KEY_ENV",
    "_ESPN_SCOREBOARD",
    "_HEADERS",
    "_ODDS_API_REGIONS",
    "_ODDS_BASE",
    "_RETRY_CONFIG",
    "_SPORTS",
    "_TIMEOUT",
    "_american_to_decimal",
    "_api_key",
    "_as_text",
    "_book_api_param",
    "_bookmaker_params",
    "_canonical_book",
    "_event_label",
    "_fetch_json",
    "_normalize_markets",
    "_resolve_event",
    "_resolve_sports",
    "_round_half",
    "_to_float",
    "logger",
    "quote",
]
