"""Parsers for freight rate sources (FBX page JSON, Drewry Infogram, FMC HTML).

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
from datetime import date
from typing import Any

from lxml import etree, html as lxml_html

from datasets.freight_data.rates_common import (
    _AGREEMENT_KEYWORDS,
    _DREWRY_DATA_RE,
    _DREWRY_SERIES,
    _FBX_CHART_RE,
    _FBX_LANES,
    _FBX_TICKER_RE,
    _REGION_HINTS,
    _cell_text,
    _infogram_cell,
    _parse_iso_date,
    _parse_money,
    _slug,
)

# ── Freightos FBX (primary) ────────────────────────────────────────────


def _fbx_records_from_page(text: str) -> list[dict[str, Any]]:
    """Extract FBX rate records from the embedded JSON on the FBX page."""
    ticker_match = _FBX_TICKER_RE.search(text)
    if not ticker_match:
        return []
    try:
        tickers = json.loads(ticker_match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(tickers, list):
        return []

    # Chart data (dated, numeric) is preferred per ticker when present.
    chart_rates: dict[str, tuple[str, float]] = {}
    chart_match = _FBX_CHART_RE.search(text)
    if chart_match:
        try:
            chart = json.loads(chart_match.group(1))
        except (json.JSONDecodeError, ValueError):
            chart = None
        if isinstance(chart, list):
            for point in chart:
                if not isinstance(point, dict):
                    continue
                ticker = str(point.get("ticker") or "").upper()
                iso = _parse_iso_date(point.get("indexDate"), ("%Y-%m-%d",))
                rate = _parse_money(point.get("value"))
                if ticker and iso and rate is not None:
                    current = chart_rates.get(ticker)
                    if current is None or iso > current[0]:
                        chart_rates[ticker] = (iso, rate)

    today = date.today().isoformat()
    records: list[dict[str, Any]] = []
    for item in tickers:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").upper()
        if not label:
            continue
        origin, destination, route = _FBX_LANES.get(label, (None, None, f"fbx-{label.lower()}"))
        dated = chart_rates.get(label)
        if dated is not None:
            iso, rate = dated
        else:
            iso, rate = today, _parse_money(item.get("value"))
        records.append(
            {
                "route": route,
                "origin": origin,
                "destination": destination,
                "rate_40ft_usd": rate,
                "index_source": "freightos_fbx",
                "date": iso,
            }
        )
    return records


# ── Drewry WCI (fallback) ──────────────────────────────────────────────


def _parse_infogram_rows(rows: list[Any]) -> tuple[str | None, list[tuple[str, float]]] | None:
    """Parse one Infogram chart's rows into (series_name, [(date, rate)]).

    Infogram row shape: ``[[None, {'value': 'Composite'}], [{'value':
    '10-Mar-16'}, {'value': '700.57'}], ...]`` — the first row carries the
    series name, following rows carry date/value cells.
    """
    if not rows or not isinstance(rows[0], list) or len(rows[0]) < 2:
        return None
    header = rows[0]
    name = _infogram_cell(header[1]) if isinstance(header[1], dict) else None
    if not name:
        name = _infogram_cell(header[0])
    points: list[tuple[str, float]] = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        date_text = _infogram_cell(row[0])
        rate = _parse_money(_infogram_cell(row[1]))
        iso = _parse_iso_date(date_text, ("%d-%b-%y", "%Y-%m-%d"))
        if iso and rate is not None:
            points.append((iso, rate))
    if not points:
        return None
    return name, points


def _iter_infogram_series(node: Any) -> list[tuple[str | None, list[tuple[str, float]]]]:
    """Collect (series_name, [(date, rate), ...]) from an Infogram blob."""
    results: list[tuple[str | None, list[tuple[str, float]]]] = []
    seen: set[int] = set()

    def walk(current: Any) -> None:
        if id(current) in seen:
            return
        seen.add(id(current))
        if isinstance(current, dict):
            data = current.get("data")
            if isinstance(data, list) and data:
                parsed = _parse_infogram_rows(data)
                if parsed is not None:
                    results.append(parsed)
            for value in current.values():
                walk(value)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(node)
    return results


def _drewry_records_from_page(text: str) -> list[dict[str, Any]]:
    """Extract WCI rate records from the Infogram embed JSON."""
    match = _DREWRY_DATA_RE.search(text)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    records: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    for name, points in _iter_infogram_series(payload):
        series_name = (name or "").strip()
        if not series_name:
            continue
        # Infogram renders en-dashes; normalise for the mapping table.
        normalized = re.sub(r"[\u2013\u2014]", "-", series_name)
        origin, destination, route = _DREWRY_SERIES.get(
            normalized, (None, None, f"wci-{_slug(normalized)}")
        )
        if route in seen_routes:
            continue
        seen_routes.add(route)
        # Latest point per series.
        iso, rate = points[-1]
        records.append(
            {
                "route": route,
                "origin": origin,
                "destination": destination,
                "rate_40ft_usd": rate,
                "index_source": "drewry_wci",
                "date": iso,
            }
        )
    return records


# ── FMC agreement library ──────────────────────────────────────────────


def _extract_carrier(name: str) -> str | None:
    """Best-effort party list from an agreement name.

    Drops the trailing agreement-type keyword ("Vessel Sharing Agreement",
    "Space Charter Agreement", ...) and returns the leading party segment.
    """
    text = (name or "").strip()
    if not text:
        return None
    carrier = text
    for keyword in _AGREEMENT_KEYWORDS:
        idx = text.lower().find(keyword.lower())
        if idx > 0:
            carrier = text[:idx]
            break
    carrier = re.sub(r"\s*[|/]\s*", " / ", carrier).strip(" -\u2013\u2014,:;/")
    return carrier or None


def _extract_trade_lanes(name: str) -> tuple[str | None, str | None]:
    """Pull up to two geography hints out of an agreement name."""
    text = (name or "").strip()
    if not text:
        return None, None
    found: list[str] = []
    lower = text.lower()
    for hint, display in _REGION_HINTS:
        if hint.lower() in lower and display not in found:
            found.append(display)
        if len(found) >= 2:
            break
    if not found:
        return None, None
    if len(found) == 1:
        return found[0], None
    return found[0], found[1]


def _derive_status(effective: str | None, last_amendment: str | None, today: date) -> str | None:
    """Heuristic status: Active when amended (or effective) within 2 years."""
    if effective is None:
        return None
    anchor = last_amendment or effective
    try:
        anchor_date = date.fromisoformat(anchor)
    except ValueError:
        return None
    return "Active" if (today - anchor_date).days <= 730 else "Historical"


def _parse_fmc_html(text: str) -> list[dict[str, Any]]:
    """Parse the FMC Agreement Library HTML table into records."""
    try:
        doc = lxml_html.fromstring(text)
    except (ValueError, etree.ParserError):
        return []
    rows = doc.cssselect("table.table-striped tr")
    today = date.today()
    records: list[dict[str, Any]] = []
    for row in rows:
        cells = row.cssselect("td")
        if len(cells) < 5:
            continue
        agreement_id = _infogram_cell(_cell_text(cells[0]))
        if not agreement_id:
            continue
        name = _cell_text(cells[2])
        effective = _parse_iso_date(_cell_text(cells[3]), ("%m/%d/%Y", "%Y-%m-%d"))
        last_amendment = _parse_iso_date(_cell_text(cells[4]), ("%m/%d/%Y", "%Y-%m-%d"))
        origin, destination = _extract_trade_lanes(name)
        records.append(
            {
                "id": agreement_id,
                "carrier": _extract_carrier(name),
                "shipper": None,  # FMC does not publish shippers (see docstring)
                "commodity": None,  # nor commodities for agreements
                "origin": origin,
                "destination": destination,
                "status": _derive_status(effective, last_amendment, today),
                "effective_date": effective,
            }
        )
    return records
