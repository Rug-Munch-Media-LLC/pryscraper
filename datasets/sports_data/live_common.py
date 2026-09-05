"""Shared constants + ESPN mapping helpers for live scores/odds.

Split out of ``live.py`` (god-file reduction). The ``live.py`` facade
re-exports everything here so the surface is unchanged.

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
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig

_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
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

_MAX_LIMIT = 100
_ODDS_API_REGIONS = "us"
_ODDS_API_MARKETS = "h2h,spreads,totals"


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


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; unparseable values map to "now"."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return datetime.now(UTC)


# ── ESPN mapping helpers ───────────────────────────────────────────────
def _status_blocks(comp: dict[str, Any], ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect status.type dicts from competition then event level."""
    blocks: list[dict[str, Any]] = []
    for source in (comp, ev):
        status = source.get("status")
        if isinstance(status, dict):
            status_type = status.get("type")
            if isinstance(status_type, dict):
                blocks.append(status_type)
    return blocks


def _is_in_progress(comp: dict[str, Any], ev: dict[str, Any]) -> bool:
    """True when ESPN reports the game state as 'in' (live)."""
    for status_type in _status_blocks(comp, ev):
        state = str(status_type.get("state") or "").lower()
        if state == "in":
            return True
        if state:
            return False  # explicit pre/post state beats absence
    return False


def _status_description(comp: dict[str, Any], ev: dict[str, Any]) -> str | None:
    """Extract ESPN's status.description (e.g. 'In Progress')."""
    for status_type in _status_blocks(comp, ev):
        description = _as_text(status_type.get("description"))
        if description:
            return description
    return None


def _clock_of(comp: dict[str, Any], ev: dict[str, Any]) -> str | None:
    """Extract ESPN's clock string (e.g. 'Q3 5:32')."""
    for status_type in _status_blocks(comp, ev):
        detail = _as_text(status_type.get("shortDetail"))
        if detail:
            return detail
    return None


def _competitors(
    comp: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract (home, away, home_score, away_score) from an ESPN competition."""
    home = away = home_score = away_score = None
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return home, away, home_score, away_score
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team")
        name = _as_text(team.get("displayName")) if isinstance(team, dict) else None
        if c.get("homeAway") == "home":
            home = name
            home_score = _as_text(c.get("score"))
        elif c.get("homeAway") == "away":
            away = name
            away_score = _as_text(c.get("score"))
    return home, away, home_score, away_score


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional 'Away @ Home' event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _live_score(comp: dict[str, Any]) -> str | None:
    """Compose the 'away - home' score string for a live competition.

    The score order matches the conventional ``"Away @ Home"`` event label
    so a record reads ``"Golden State Warriors @ Phoenix Suns" /
    "50 - 45"``.
    """
    _home, _away, home_score, away_score = _competitors(comp)
    if home_score is None or away_score is None:
        return None
    return f"{away_score} - {home_score}"
