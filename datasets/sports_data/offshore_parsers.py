"""Generic odds parsers for standalone offshore books.

Two conservative parsers shared by the standalone (non-BetOnline-family)
offshore books and the European book modules:

* :func:`_parse_embedded_state` — best-effort walk of a
  ``window.__INITIAL_STATE__``-style JSON blob (JS-heavy SPA books).
* :func:`_parse_decimal_rows` — conservative HTML row parser for SSR'd
  decimal-odds pages.

Both never raise; both return ``[]`` when the page yields nothing
(JS-rendered books degrade honestly to empty, never silently to "no odds"
without the block being flagged upstream by the transport layer).

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
import re
from typing import Any

import datasets.sports_data.sources as sources
from datasets.sports_data.offshore_books import (
    _american_to_decimal,
    _event_label,
)
from datasets.sports_data.sources import _as_text, _classes, _from_html, _to_float

# Decimal odds token (e.g. "2.10") vs. US odds (e.g. "+110" / "-120") used
# by the generic row parser.
_DECIMAL_ODDS_RE = re.compile(r"^\d+\.\d{2}$")
_US_ODDS_RE = re.compile(r"[+-]\d{3,4}\b")


def _parse_embedded_state(html: str, sport: str, book: str, bookmaker: str) -> list[dict[str, Any]]:
    """Best-effort walk of a ``window.__INITIAL_STATE__``-style JSON blob.

    Mirrors the BookMaker-family shape (``gameId`` / ``homeTeam`` /
    ``awayTeam`` / ``gameData[].lineDict.MoneyLine``) that the BetOnline
    parser in :mod:`sports_data.sources` already handles, plus a looser
    fallback that recognises any nested object carrying two team names and a
    two-sided decimal odds dict.
    """
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
            sources._record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=_as_text(event.get("wagerCutOff")),
                source="offshore",
            )
        )
    return records


def _parse_decimal_rows(html: str, sport: str, book: str, bookmaker: str) -> list[dict[str, Any]]:
    """Conservative generic HTML row parser for SSR'd decimal-odds pages.

    Walks ``<tr>``/``<div>`` containers whose class hints at a game row and
    requires at least two team-like text nodes and two decimal odds in the
    same container before emitting an h2h record. Two odds -> 2-way; three
    odds -> 3-way (draw in the middle). Never raises; returns ``[]`` when the
    page has no such rows (JS-rendered books degrade honestly to empty).
    """
    tree = _from_html(html)
    if tree is None:
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for el in tree.iter():
        if el.tag not in ("tr", "div"):
            continue
        cls = _classes(el)
        if not re.search(r"row|game|coupon|match|event|odds", cls, re.I):
            continue
        texts: list[str] = []
        for node in el.itertext():
            text = _as_text(node)
            if text is not None:
                texts.append(text)
        odds = [t for t in texts if _DECIMAL_ODDS_RE.match(t)]
        teams = [
            t
            for t in texts
            if not _DECIMAL_ODDS_RE.match(t) and _US_ODDS_RE.search(t) is None and 2 <= len(t) <= 40
        ]
        if len(teams) < 2 or len(odds) < 2:
            continue
        home, away = teams[0], teams[1]
        key = f"{home}|{away}|{tuple(odds)}"
        if key in seen:
            continue
        seen.add(key)
        draw_value = _to_float(odds[1]) if len(odds) >= 3 else None
        if len(odds) >= 3 and draw_value is not None and 0 < draw_value < 10:
            home_odds, away_odds = _to_float(odds[0]), _to_float(odds[2])
            draw_odds = draw_value
        else:
            home_odds, away_odds = _to_float(odds[0]), _to_float(odds[1])
            draw_odds = None
        if home_odds is None and away_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            sources._record(
                sport=sport,
                event=event_label,
                event_id=None,
                market="h2h",
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                draw_odds=draw_odds,
                last_update=None,
                source="offshore",
            )
        )
    return records
