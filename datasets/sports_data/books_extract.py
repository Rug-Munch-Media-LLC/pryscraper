"""Payload-level extraction for the sportsbook registry scrapers.

Turns a fetched payload (raw JSON feed or HTML page) into normalized odds
records: embedded-state discovery (``__NEXT_DATA__``, ``__NUXT__``,
``__INITIAL_STATE__``, ``_dida_config_``, JSON-LD via Pry's
:mod:`pry.engine.network`), JSON-tree walking via
:mod:`datasets.sports_data.books_markets`, plain HTML ``<table>`` parsing
(lxml, guarded) and record deduplication.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import re
from typing import Any

from datasets.sports_data.books_markets import _walk_json
from datasets.sports_data.books_normalize import _decimal_odds, _make_record

logger = logging.getLogger(__name__)

# ── Guarded reuse of Pry's own network extractors (never a hard dep) ─────
_extract_nextjs_props: Any = None
_extract_nuxt_state: Any = None
_extract_json_ld: Any = None
if importlib.util.find_spec("pry.engine.network") is not None:
    from pry.engine.network import (
        extract_json_ld as _extract_json_ld,
        extract_nextjs_props as _extract_nextjs_props,
        extract_nuxt_state as _extract_nuxt_state,
    )


# ── Embedded-state extraction (reuse network.py + local parsers) ────────
def _parse_braced_json(text: str, start: int) -> dict[str, Any] | None:
    """Parse a JSON object starting at ``text[start]`` using brace counting."""
    if start < 0 or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed: Any = json.loads(text[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _extract_init_state(html: str) -> dict[str, Any] | None:
    """Extract ``window.__INITIAL_STATE__ = {...}``."""
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{)", html, re.DOTALL)
    if match:
        return _parse_braced_json(html, match.start(1))
    return None


def _extract_dida_config(html: str) -> dict[str, Any] | None:
    """Extract ``window._dida_config_ = {...}`` (SBTech-style books)."""
    match = re.search(r"(?:window\.)?_dida_config_\s*=\s*(\{)", html, re.DOTALL)
    if match:
        return _parse_braced_json(html, match.start(1))
    return None


def _embedded_states(html: str) -> list[dict[str, Any]]:
    """All embedded JSON states in an HTML page, in priority order."""
    states: list[dict[str, Any]] = []
    if _extract_nextjs_props is not None:
        with contextlib.suppress(Exception):
            data = _extract_nextjs_props(html)
            if isinstance(data, dict):
                states.append(data)
    if _extract_nuxt_state is not None:
        with contextlib.suppress(Exception):
            data = _extract_nuxt_state(html)
            if isinstance(data, dict):
                states.append(data)
    init_state = _extract_init_state(html)
    if init_state is not None:
        states.append(init_state)
    dida_config = _extract_dida_config(html)
    if dida_config is not None:
        states.append(dida_config)
    if _extract_json_ld is not None:
        with contextlib.suppress(Exception):
            for data in _extract_json_ld(html):
                if isinstance(data, dict):
                    states.append(data)
    return states


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Plain HTML table extraction (lxml, guarded) ──────────────────────────
_lxml_html: Any = None
_lxml_etree: Any = None
if importlib.util.find_spec("lxml") is not None:
    import lxml.etree
    import lxml.html

    _lxml_html = lxml.html
    _lxml_etree = lxml.etree


def _records_from_html_tables(
    book: dict[str, Any],
    html_text: str,
    sport: str,
    market: str,
) -> list[dict[str, Any]]:
    """Extract h2h records from server-rendered odds tables (``<td>`` rows)."""
    if market not in ("h2h", "all") or _lxml_html is None:
        return []
    try:
        tree = _lxml_html.fromstring(html_text)
    except (_lxml_etree.ParserError, ValueError) as exc:
        logger.warning(
            "books_html_parse_failed",
            extra={"book": book.get("id"), "error": str(exc)[:120]},
        )
        return []
    records: list[dict[str, Any]] = []
    for table in tree.xpath("//table"):
        for row in table.xpath(".//tr"):
            cells = [cell.text_content().strip() for cell in row.xpath("./td")]
            if len(cells) < 4:
                continue
            home, away = cells[0], cells[1]
            home_odds = _decimal_odds(cells[2])
            away_odds = _decimal_odds(cells[3])
            if home and away and home_odds is not None and away_odds is not None:
                records.append(
                    _make_record(
                        book,
                        sport,
                        f"{home} @ {away}",
                        "h2h",
                        home,
                        away,
                        home_odds,
                        away_odds,
                        None,
                        None,
                        None,
                    )
                )
    return records


# ── Payload → records ────────────────────────────────────────────────────
def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("home")),
            str(record.get("away")),
            str(record.get("market")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _records_from_payload(
    book: dict[str, Any],
    payload: str,
    kind: str,
    sport: str,
    market: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Extract + normalize records from a fetched payload (never raises)."""
    if limit <= 0:
        return []
    try:
        records: list[dict[str, Any]] = []
        if kind == "json":
            data = _parse_json(payload)
            if isinstance(data, (dict, list)):
                records = _walk_json(data, book, sport, market, limit)
            return _dedupe(records)[:limit]
        for state in _embedded_states(payload):
            records.extend(_walk_json(state, book, sport, market, limit - len(records)))
            if len(records) >= limit:
                return _dedupe(records)[:limit]
        records.extend(_records_from_html_tables(book, payload, sport, market))
        return _dedupe(records)[:limit]
    except Exception:  # noqa: BLE001 - extraction must never raise
        logger.warning("books_extraction_failed", extra={"book_id": book["id"]})
        return []
