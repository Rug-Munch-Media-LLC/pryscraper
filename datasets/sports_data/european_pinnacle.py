"""Pinnacle fetcher — semi-public guest JSON API for Pry.

Extracted from :mod:`datasets.sports_data.european`. Pinnacle is the
sharpest book: the guest API (``guest.api.pinnacle.com/v1``: ``/leagues``,
``/fixtures``, ``/odds``) needs no auth and serves decimal odds — the
sharp line for CLV / no-vig consensus.

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
from typing import Any
from urllib.parse import urlencode

import httpx

import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from datasets.sports_data.european_common import (
    _PINNACLE_LEAGUE_KEYWORDS,
    _PINNACLE_SPORTS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.offshore import _fetch_json_geo
from datasets.sports_data.sources import _as_text, _to_float

logger = logging.getLogger(__name__)

# Guarded import: sports_data.odds helpers are optional (parallel build).
try:
    from datasets.sports_data.odds import _american_to_decimal, _event_label
except ImportError:  # pragma: no cover - parallel build guard
    _american_to_decimal = None  # type: ignore[assignment]
    _event_label = None  # type: ignore[assignment]

# ── Pinnacle (guest JSON API) ───────────────────────────────────────────
_PINNACLE_LEAGUES = "https://guest.api.pinnacle.com/v1/leagues"
_PINNACLE_FIXTURES = "https://guest.api.pinnacle.com/v1/fixtures"
_PINNACLE_ODDS = "https://guest.api.pinnacle.com/v1/odds"


async def _pinnacle_league_ids(sport: str, sport_id: int) -> list[int]:
    """League ids for a sport, narrowed by league keyword when configured."""
    keyword = _PINNACLE_LEAGUE_KEYWORDS.get(sport)
    if keyword is None:
        return []
    url = f"{_PINNACLE_LEAGUES}?{urlencode({'sportId': sport_id})}"
    payload = await _fetch_json_geo(url)
    if not isinstance(payload, dict):
        return []
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        return []
    return [
        int(league["id"])
        for league in leagues
        if isinstance(league, dict) and keyword in str(league.get("name") or "").lower()
    ]


def _pinnacle_price(value: Any) -> float | None:
    """Decimal odds from a Pinnacle price (decimal when DECIMAL format)."""
    number = _to_float(value)
    if number is None:
        return None
    if number > 0:
        return round(number, 2)
    # American-format fallback (-110 / +110).
    if _american_to_decimal is None:
        return None
    return _american_to_decimal(value)


async def _parse_pinnacle_sport(
    canonical: str, sport_id: int, league_ids: list[int], limit: int
) -> list[dict[str, Any]]:
    """Fetch fixtures + odds for a Pinnacle sport and join them into records."""
    params: dict[str, Any] = {"sportId": sport_id, "isLive": 0, "oddsFormat": "DECIMAL"}
    if league_ids:
        params["leagueIds"] = ",".join(str(i) for i in league_ids)
    query = urlencode(params)
    fixtures = await _fetch_json_geo(f"{_PINNACLE_FIXTURES}?{query}")
    odds = await _fetch_json_geo(f"{_PINNACLE_ODDS}?{query}")
    events_by_id: dict[int, dict[str, Any]] = {}
    if isinstance(fixtures, dict):
        for league in fixtures.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            for event in league.get("events") or []:
                if isinstance(event, dict) and isinstance(event.get("id"), int):
                    events_by_id[event["id"]] = event
    records: list[dict[str, Any]] = []
    if not isinstance(odds, dict):
        return []
    for league in odds.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        for event in league.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            fixture = events_by_id.get(event_id) if isinstance(event_id, int) else None
            home = _as_text((fixture or {}).get("home"))
            away = _as_text((fixture or {}).get("away"))
            if not home or not away:
                continue
            last_update = _as_text((fixture or {}).get("starts"))
            event_label = (
                f"{away} @ {home}"
                if _event_label is None
                else (_event_label(home, away) or f"{away} @ {home}")
            )
            periods = event.get("periods")
            if not isinstance(periods, list):
                continue
            for period in periods:
                if not isinstance(period, dict):
                    continue
                moneyline = period.get("moneyline")
                if isinstance(moneyline, dict):
                    home_odds = _pinnacle_price(moneyline.get("home"))
                    away_odds = _pinnacle_price(moneyline.get("away"))
                    if home_odds is not None and away_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="h2h",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=home_odds,
                                away_odds=away_odds,
                                last_update=last_update,
                                source="european",
                            )
                        )
                spread = period.get("spread")
                if isinstance(spread, dict):
                    line = _to_float(spread.get("hdp"))
                    home_odds = _pinnacle_price(spread.get("home"))
                    away_odds = _pinnacle_price(spread.get("away"))
                    if home_odds is not None and away_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="spreads",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=home_odds,
                                away_odds=away_odds,
                                spread=line,
                                last_update=last_update,
                                source="european",
                            )
                        )
                total = period.get("total")
                if isinstance(total, dict):
                    line = _to_float(total.get("points"))
                    over_odds = _pinnacle_price(total.get("over"))
                    under_odds = _pinnacle_price(total.get("under"))
                    if over_odds is not None and under_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="totals",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=over_odds,
                                away_odds=under_odds,
                                total=line,
                                last_update=last_update,
                                source="european",
                            )
                        )
    return records[: max(1, int(limit or 50))]


async def fetch_pinnacle(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Pinnacle odds for one sport via the guest JSON API.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).
        limit: Max records to return.

    Returns:
        Canonical h2h/spreads/totals records tagged ``source="european"``;
        ``[]`` on any failure. Never raises.
    """
    name = "pinnacle"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        sport_id = _PINNACLE_SPORTS.get(canonical)
        if sport_id is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        league_ids = await _pinnacle_league_ids(canonical, sport_id)
        records = await _parse_pinnacle_sport(canonical, sport_id, league_ids, limit)
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
