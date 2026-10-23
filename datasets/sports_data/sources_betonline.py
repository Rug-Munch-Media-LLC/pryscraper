"""BetOnline listing-page scrape fetcher for the multi-source odds feed.

BetOnline (``www.betonline.ag``) is an offshore book; no public JSON API,
so this fetcher parses the sportsbook listing pages (best-effort; the
listing markup is server-rendered HTML with inline US-format odds) and an
embedded ``window.__INITIAL_STATE__`` blob when present.

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

import json
import logging
import re
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
    _classes,
    _from_html,
    _looks_blocked,
    _record,
    _to_float,
)

logger = logging.getLogger(__name__)

# ── BetOnline (listing-page scrape, no public API) ──────────────────────
_BETONLINE_BASE = "https://www.betonline.ag/sportsbook"
_GAME_HREF_RE = re.compile(r"/sportsbook/[^/]+/[^/]+/game/(\d+)", re.I)
_US_ODDS_RE = re.compile(r"[+-]\d{3,4}\b")
_TEAM_CLASS_RE = re.compile(r"team|participant|name", re.I)


def _container_text(el: Any) -> str:
    try:
        return el.text_content() or ""
    except (AttributeError, TypeError) as exc:
        logger.debug("betonline_container_text_failed", extra={"error": str(exc)[:120]})
        return ""


def _team_names_from_container(container: Any) -> list[str]:
    """Best-effort team names from a game row container."""
    candidates: list[str] = []
    for el in container.iter():
        cls = _classes(el)
        if not _TEAM_CLASS_RE.search(cls):
            continue
        text = _as_text(el.text_content())
        if text and _US_ODDS_RE.search(text) is None:
            candidates.append(text)
    if len(candidates) >= 2:
        return candidates[:2]
    # Fallback: the two longest non-odds text nodes in the row.
    texts: list[str] = []
    for node in container.itertext():
        node_text = _as_text(node)
        if node_text and _US_ODDS_RE.search(node_text) is None and 3 <= len(node_text) <= 40:
            texts.append(node_text)
    texts = sorted(set(texts), key=len, reverse=True)
    return texts[:2]


def _parse_betonline_html(html: str, sport: str) -> list[dict[str, Any]]:
    """Parse the sportsbook listing page into h2h records (best-effort)."""
    tree = _from_html(html)
    if tree is None:
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in tree.iter("a"):
        href = a.get("href") or ""
        match = _GAME_HREF_RE.search(href)
        if not match:
            continue
        game_id = match.group(1)
        if game_id in seen:
            continue
        seen.add(game_id)
        container: Any = a
        for _depth in range(8):
            parent = container.getparent()
            if parent is None:
                break
            container = parent
        container_text = _container_text(container)
        odds_tokens = _US_ODDS_RE.findall(container_text)
        teams = _team_names_from_container(container)
        if len(teams) < 2 or len(odds_tokens) < 2:
            continue
        away, home = teams[0], teams[1]  # sportsbook convention: away first
        away_odds = (
            _american_to_decimal(odds_tokens[0]) if _american_to_decimal is not None else None
        )
        home_odds = (
            _american_to_decimal(odds_tokens[1]) if _american_to_decimal is not None else None
        )
        if away_odds is None and home_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            _record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book="betonline",
                bookmaker="BetOnline",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=None,
                source="betonline",
            )
        )
    return records


def _parse_betonline_embedded_json(html: str, sport: str) -> list[dict[str, Any]]:
    """Parse a ``window.__INITIAL_STATE__``-style JSON blob, if embedded."""
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    events: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "gameId" in node and ("homeTeam" in node or "gameData" in node):
                events.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    records: list[dict[str, Any]] = []
    for event in events:
        game_id = _as_text(event.get("gameId"))
        home = _as_text(event.get("homeTeam"))
        away = _as_text(event.get("awayTeam"))
        if not home or not away or _american_to_decimal is None:
            continue
        game_data = event.get("gameData")
        if not isinstance(game_data, list):
            continue
        home_odds = away_odds = None
        for period in game_data:
            if not isinstance(period, dict):
                continue
            line_type = str(period.get("lineType") or "")
            line_dict = period.get("lineDict")
            if not isinstance(line_dict, dict):
                continue
            money = line_dict.get("MoneyLine")
            if not isinstance(money, dict):
                continue
            value = _as_text(money.get("decimalLine")) or _as_text(money.get("line"))
            if line_type == "AwayLine":
                away_odds = _to_float(value)
            elif line_type == "HomeLine":
                home_odds = _to_float(value)
        if home_odds is None and away_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            _record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book="betonline",
                bookmaker="BetOnline",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=_as_text(event.get("wagerCutOff")),
                source="betonline",
            )
        )
    return records


async def fetch_betonline(sport: str) -> list[dict[str, Any]]:
    """Fetch one sport's odds from BetOnline's sportsbook listing pages.

    BetOnline publishes no public JSON API, so this is a best-effort parse
    of the server-rendered listing HTML (game links + inline US odds) and of
    an embedded ``window.__INITIAL_STATE__`` blob when present.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).

    Returns:
        Canonical h2h records tagged ``source="betonline"``; ``[]`` on any
        failure. Never raises.
    """
    from datasets.sports_data import sources as _base

    name = "betonline"
    start = _base._monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _base._BETONLINE_SPORTS.get(canonical)
        if route is None:
            return []
        sport_slug, league = route
        url = f"{_BETONLINE_BASE}/{sport_slug}"
        if league:
            url = f"{url}/{league}"
        html = await _base._fetch_text(url)
        if html is None:
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            _base._mark(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="anti-bot block",
            )
            return []
        records = _parse_betonline_embedded_json(html, canonical)
        if not records:
            records = _parse_betonline_html(html, canonical)
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
        logger.warning("sports_betonline_failed", extra={"sport": sport})
        _base._mark(
            name,
            ok=False,
            latency_ms=int((_base._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
