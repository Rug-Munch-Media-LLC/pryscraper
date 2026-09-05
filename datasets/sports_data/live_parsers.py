"""Record mapping for live scores/odds (ESPN + The Odds API payloads).

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

from datetime import UTC, datetime
from typing import Any

from datasets.sports_data.live_common import (
    _as_text,
    _clock_of,
    _competitors,
    _event_label,
    _is_in_progress,
    _live_score,
    _parse_iso,
    _status_description,
    _to_float,
)


# ── Live scores mapping ────────────────────────────────────────────────
def _map_live_scores(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map one ESPN scoreboard payload onto in-progress score records."""
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    records: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        if not _is_in_progress(comp, ev):
            continue
        home, away, home_score, away_score = _competitors(comp)
        if not home or not away:
            continue
        records.append(
            {
                "sport": sport_slug,
                "event": _event_label(home, away),
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": _status_description(comp, ev) or "In Progress",
                "clock": _clock_of(comp, ev),
                "last_update": None,
            }
        )
    return records


# ── Live odds mapping (ESPN) ───────────────────────────────────────────
def _map_espn_live_odds(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map the ``odds`` blocks of in-progress ESPN competitions."""
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    records: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        if not _is_in_progress(comp, ev):
            continue
        home, away, _home_score, _away_score = _competitors(comp)
        event = _event_label(home, away)
        if not event:
            continue
        score = _live_score(comp)
        clock = _clock_of(comp, ev)
        odds_list = comp.get("odds")
        if not isinstance(odds_list, list):
            continue
        for odd in odds_list:
            if not isinstance(odd, dict):
                continue
            provider = odd.get("provider")
            book = _as_text(provider.get("name")) if isinstance(provider, dict) else None
            if not book:
                continue
            spread = _to_float(odd.get("spread"))
            total = _to_float(odd.get("overUnder"))
            if spread is not None:
                records.append(
                    {
                        "event": event,
                        "market": "spread",
                        "book": book,
                        "odds": spread,
                        "live_score": score,
                        "clock": clock,
                        "last_update": None,
                    }
                )
            if total is not None:
                records.append(
                    {
                        "event": event,
                        "market": "total",
                        "book": book,
                        "odds": total,
                        "live_score": score,
                        "clock": clock,
                        "last_update": None,
                    }
                )
    return records


# ── Live odds mapping (The Odds API) ───────────────────────────────────
def _map_odds_api_live(payload: list[Any]) -> list[dict[str, Any]]:
    """Map in-play The Odds API events (commence_time in the past) onto records."""
    now = datetime.now(UTC)
    records: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        commence = _as_text(raw.get("commence_time"))
        if commence is None or _parse_iso(commence) >= now:
            continue  # only events that have started count as live
        home = _as_text(raw.get("home_team"))
        away = _as_text(raw.get("away_team"))
        event = _event_label(home, away)
        if not event:
            continue
        bookmakers = raw.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for bk in bookmakers:
            if not isinstance(bk, dict):
                continue
            book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
            if not book:
                continue
            last_update = _as_text(bk.get("last_update")) or commence
            markets = bk.get("markets")
            if not isinstance(markets, list):
                continue
            for mkt in markets:
                if not isinstance(mkt, dict):
                    continue
                market = _as_text(mkt.get("key")) or "h2h"
                outcomes = mkt.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    price = _to_float(outcome.get("price"))
                    if price is None:
                        continue
                    records.append(
                        {
                            "event": event,
                            "market": market,
                            "book": book,
                            "odds": price,
                            "live_score": None,
                            "clock": None,
                            "last_update": last_update,
                        }
                    )
    return records
