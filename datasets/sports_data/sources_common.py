"""Shared helpers + registries for the multi-source sports odds fetchers.

Pure, dependency-light pieces every ``sports_data.sources`` submodule
shares: canonical record building, team/label normalization, fuzzy
cross-source event identity, anti-bot block detection, HTML utilities and
the per-source sport routing tables. No network here — transport lives in
:mod:`sports_data.sources`.

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
import re
from typing import Any

from lxml import html as _lxml_html

# Odds-side helpers are defined in odds_common (dependency-free), so this
# import is always safe — no guarded parallel-build fallback needed.
from datasets.sports_data.odds_common import (
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _canonical_book as _canonical_book,
    _event_label as _event_label,
    _resolve_sports as _resolve_sports,
)

logger = logging.getLogger(__name__)


# ── Shared record / normalization helpers ───────────────────────────────
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
    """Normalize a team name for fuzzy cross-source matching.

    Lowercases, strips punctuation and joins the remaining words so
    ``"Boston Celtics"`` -> ``"boston celtics"`` and short names match
    their full forms by substring containment.
    """
    if name is None:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", str(name).lower()))


def _split_label(label: Any) -> list[str]:
    """Split an event label like ``"Celtics @ Lakers"`` into team names."""
    if not label:
        return []
    parts = re.split(r"\s*(?:@|vs\.?|v|at|-)\s*", str(label).strip(), flags=re.I)
    teams: list[str] = []
    for part in parts:
        team = _normalize_team(part)
        if len(team) >= 3:
            teams.append(team)
    return teams


def _record_teams(record: dict[str, Any]) -> list[str]:
    """Team names of a record, preferring the home/away fields."""
    home = _normalize_team(record.get("home"))
    away = _normalize_team(record.get("away"))
    if home or away:
        return [t for t in (home, away) if len(t) >= 3]
    return _split_label(record.get("event"))


def _normalize_label(label: Any) -> str:
    """Canonical label key: lowercase alnum tokens, no separators."""
    return " ".join(sorted(set(re.findall(r"[a-z0-9]+", str(label or "").lower()))))


def _teams_contain(needles: list[str], haystack: list[str]) -> bool:
    """True when every needle team is contained in (or contains) a haystack team."""
    if not needles or not haystack:
        return False
    return all(any(needle in hm or hm in needle for hm in haystack) for needle in needles)


def same_event(record_a: dict[str, Any], record_b: dict[str, Any]) -> bool:
    """Fuzzy event identity across sources.

    Two records are the same event when their home/away teams match by
    containment in both directions (``"Celtics"`` == ``"Boston Celtics"``,
    and order-independent — ``"Celtics @ Lakers"`` == ``"Lakers vs
    Celtics"``). Records without usable team fields fall back to exact
    normalized label equality.
    """
    teams_a = _record_teams(record_a)
    teams_b = _record_teams(record_b)
    if teams_a and teams_b:
        return _teams_contain(teams_a, teams_b) and _teams_contain(teams_b, teams_a)
    label_a = _normalize_label(record_a.get("event"))
    label_b = _normalize_label(record_b.get("event"))
    return bool(label_a) and label_a == label_b


def event_matches(record: dict[str, Any], label: str | None) -> bool:
    """True when a record's event matches a target label (e.g. from odds.py)."""
    target = _split_label(label)
    if not target:
        return False
    teams = _record_teams(record)
    if not teams:
        return _normalize_label(record.get("event")) == _normalize_label(label)
    return _teams_contain(target, teams) or _teams_contain(teams, target)


def _event_id_matches(record: dict[str, Any], event_id: str | None) -> bool:
    if not event_id:
        return False
    return str(record.get("event_id") or "") == str(event_id).strip()


# ── Anti-bot / block detection (honest flagging) ────────────────────────
_BLOCK_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "just a moment",
    "checking your browser",
    "attention required",
    "access denied",
    "captcha",
    "forbidden",
    "too many requests",
    "data is temporarily unavailable",
)


def _looks_blocked(text: str) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _from_html(html: str) -> Any | None:
    """Parse HTML into an lxml tree; ``None`` on malformed input."""
    if not html or not html.strip():
        return None
    try:
        return _lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - lxml raises assorted parse errors on hostile HTML
        logger.warning("sports_sources_html_parse_failed")
        return None


def _classes(element: Any) -> str:
    """Normalized class attribute of an lxml element (string or list)."""
    value = element.get("class")
    if isinstance(value, list):
        return " ".join(value)
    return " ".join(str(value or "").split())


# ── Sport routing ───────────────────────────────────────────────────────
# Canonical sport slug -> (source-specific path, market coverage).
_ODDSPORTAL_SPORTS: dict[str, tuple[str, str]] = {
    "basketball_nba": ("basketball/usa/nba", "basketball"),
    "basketball_ncaab": ("basketball/usa/ncaa", "basketball"),
    "americanfootball_nfl": ("americanfootball/usa/nfl", "americanfootball"),
    "americanfootball_ncaaf": ("americanfootball/usa/ncaa", "americanfootball"),
    "baseball_mlb": ("baseball/usa/mlb", "baseball"),
    "icehockey_nhl": ("icehockey/usa/nhl", "icehockey"),
    "soccer_epl": ("soccer/england/premier-league", "soccer"),
    "soccer_spain_la_liga": ("soccer/spain/laliga", "soccer"),
    "soccer_germany_bundesliga": ("soccer/germany/bundesliga", "soccer"),
    "soccer_italy_serie_a": ("soccer/italy/serie-a", "soccer"),
    "tennis_atp": ("tennis/atp", "tennis"),
    "tennis_wta": ("tennis/wta", "tennis"),
    "mma_mixed_martial_arts": ("mma/ufc", "mma"),
    "boxing": ("boxing", "boxing"),
    "formula_1": ("racing/formula-1", "racing"),
    "golf_pga": ("golf/usa/pga", "golf"),
    "cricket_international_t20": ("cricket/international/t20", "cricket"),
}

_BOVADA_SPORTS: dict[str, tuple[str, str | None]] = {
    "basketball_nba": ("basketball", "nba"),
    "basketball_ncaab": ("basketball", "ncaa"),
    "americanfootball_nfl": ("football", "nfl"),
    "americanfootball_ncaaf": ("football", "ncaa"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "soccer_epl": ("soccer", "england"),
    "soccer_spain_la_liga": ("soccer", "spain"),
    "soccer_germany_bundesliga": ("soccer", "germany"),
    "soccer_italy_serie_a": ("soccer", "italy"),
    "tennis_atp": ("tennis", None),
    "tennis_wta": ("tennis", None),
    "mma_mixed_martial_arts": ("mma", None),
    "boxing": ("boxing", None),
}

_BETONLINE_SPORTS: dict[str, tuple[str, str | None]] = {
    "basketball_nba": ("basketball", "nba"),
    "basketball_ncaab": ("basketball", "ncaa"),
    "americanfootball_nfl": ("football", "nfl"),
    "americanfootball_ncaaf": ("football", "ncaa"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "soccer_epl": ("soccer", "england"),
    "soccer_spain_la_liga": ("soccer", "spain"),
    "soccer_germany_bundesliga": ("soccer", "germany"),
    "soccer_italy_serie_a": ("soccer", "italy"),
    "tennis_atp": ("tennis", None),
    "tennis_wta": ("tennis", None),
    "mma_mixed_martial_arts": ("mma", None),
    "boxing": ("boxing", None),
}


def source_supports(source: str, sport: str) -> bool:
    """True when a source maps the sport (canonical slug or short alias)."""
    if source not in ("oddsportal", "bovada", "betonline") or _resolve_sports is None:
        return False
    slugs = _resolve_sports(sport)
    if not slugs:
        return False
    canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
    if source == "oddsportal":
        return canonical in _ODDSPORTAL_SPORTS
    if source == "bovada":
        return canonical in _BOVADA_SPORTS
    return canonical in _BETONLINE_SPORTS
