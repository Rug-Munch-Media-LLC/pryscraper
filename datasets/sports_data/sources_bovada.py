"""Bovada public JSON feed fetcher for the multi-source sports odds feed.

Bovada (``www.bovada.lv``) is an offshore book with a public JSON odds
feed (``/services/sports/event/v2/events/A/description/{sport}[/{league}]``).
Returns h2h, spreads and totals as decimal odds. Expect geo-blocks.

Transport (fetch/cache/health) lives in :mod:`sports_data.sources` and is
reached through a late module handle so test monkeypatches keep working.

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

import httpx

from datasets.sports_data.odds_common import (
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _event_label as _event_label,
    _resolve_sports as _resolve_sports,
)
from datasets.sports_data.sources_common import (
    _as_text,
    _normalize_team,
    _record,
    _split_label,
    _to_float,
)

logger = logging.getLogger(__name__)

# ── Bovada (public JSON feed) ───────────────────────────────────────────
_BOVADA_BASE = "https://www.bovada.lv/services/sports/event/v2/events/A/description"
# Market keys on the Bovada feed.
_BOVADA_ML_KEY = {"2W-12", "2W-ML", "2W-1X2"}
_BOVADA_SPREAD_KEY = {"2W-HCAP", "2W-SP"}
_BOVADA_TOTAL_KEY = {"2W-OU", "2W-TT"}


def _bovada_side(outcome: dict[str, Any], home: str | None, away: str | None) -> str | None:
    """Map a Bovada outcome to 'home'/'away'/'over'/'under' or None."""
    otype = str(outcome.get("type") or "").upper()
    if otype == "H":
        return "home"
    if otype == "A":
        return "away"
    if otype == "O":
        return "over"
    if otype == "U":
        return "under"
    o_name = _normalize_team(outcome.get("description") or outcome.get("name") or "")
    if o_name:
        if home and o_name == _normalize_team(home):
            return "home"
        if away and o_name == _normalize_team(away):
            return "away"
    return None


def _bovada_price(outcome: dict[str, Any]) -> float | None:
    """Decimal odds from a Bovada outcome's price object."""
    price = outcome.get("price")
    if not isinstance(price, dict):
        return None
    decimal = _to_float(price.get("decimal"))
    if decimal is not None and decimal > 0:
        return round(decimal, 2)
    american = _to_float(price.get("american"))
    if american is not None and _american_to_decimal is not None:
        return _american_to_decimal(american)
    return None


def _bovada_handicap(outcome: dict[str, Any]) -> float | None:
    price = outcome.get("price")
    if not isinstance(price, dict):
        return None
    return _to_float(price.get("handicap"))


def _parse_bovada_event(event: dict[str, Any], sport: str) -> list[dict[str, Any]]:
    """Map one Bovada event onto canonical h2h/spreads/totals records."""
    competitors = event.get("competitors")
    home = away = None
    if isinstance(competitors, list):
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            comp_name = _as_text(comp.get("name"))
            if not comp_name:
                continue
            if comp.get("home") is True or str(comp.get("homeAway") or "").lower() == "home":
                home = comp_name
            elif away is None:
                away = comp_name
    if not home or not away:
        parsed = _split_label(event.get("description"))
        if len(parsed) >= 2:
            away, home = parsed[0], parsed[1]
    if not home or not away:
        return []
    event_label = (
        f"{away} @ {home}"
        if _event_label is None
        else (_event_label(home, away) or f"{away} @ {home}")
    )
    event_id = _as_text(event.get("id"))
    last_update = _as_text(event.get("lastModified")) or _as_text(event.get("startTime"))
    records: list[dict[str, Any]] = []
    groups = event.get("displayGroups")
    if not isinstance(groups, list):
        return []
    for group in groups:
        if not isinstance(group, dict):
            continue
        markets = group.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            key = str(market.get("key") or "")
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            if key in _BOVADA_ML_KEY:
                odds: dict[str, float] = {}
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if side in {"home", "away"} and price is not None:
                        odds[side] = price
                if odds:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="h2h",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=odds.get("home"),
                            away_odds=odds.get("away"),
                            last_update=last_update,
                            source="bovada",
                        )
                    )
            elif key in _BOVADA_SPREAD_KEY:
                spread_odds: dict[str, float] = {}
                line: float | None = None
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if side in {"home", "away"} and price is not None:
                        spread_odds[side] = price
                        if line is None:
                            line = _bovada_handicap(outcome)
                if spread_odds:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="spreads",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=spread_odds.get("home"),
                            away_odds=spread_odds.get("away"),
                            spread=line,
                            last_update=last_update,
                            source="bovada",
                        )
                    )
            elif key in _BOVADA_TOTAL_KEY:
                over_price = under_price = None
                total_line: float | None = None
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if price is None:
                        continue
                    if side == "over":
                        over_price = price
                        total_line = _bovada_handicap(outcome)
                    elif side == "under":
                        under_price = price
                if over_price is not None or under_price is not None:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="totals",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=over_price,
                            away_odds=under_price,
                            total=total_line,
                            last_update=last_update,
                            source="bovada",
                        )
                    )
    return records


async def fetch_bovada(sport: str) -> list[dict[str, Any]]:
    """Fetch one sport's odds from Bovada's public JSON feed.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).

    Returns:
        Canonical h2h/spreads/totals records tagged ``source="bovada"``;
        ``[]`` on any failure (unsupported sport, network error, geo-block).
        Never raises.
    """
    from datasets.sports_data import sources as _base

    name = "bovada"
    start = _base._monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _base._BOVADA_SPORTS.get(canonical)
        if route is None:
            return []
        sport_slug, league = route
        url = f"{_BOVADA_BASE}/{sport_slug}"
        if league:
            url = f"{url}/{league}"
        payload = await _base._fetch_json(url)
        if payload is None:
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="unexpected payload",
            )
            return []
        events = payload[0].get("events")
        if not isinstance(events, list):
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="no events",
            )
            return []
        records: list[dict[str, Any]] = []
        for event in events:
            if isinstance(event, dict):
                records.extend(_parse_bovada_event(event, canonical))
        if not records:
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _base._mark(name, ok=True, latency_ms=int((_base._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_bovada_failed", extra={"sport": sport})
        _base._mark(
            name,
            ok=False,
            latency_ms=int((_base._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
