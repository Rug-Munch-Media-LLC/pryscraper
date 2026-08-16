"""Container freight intelligence — Freightos FBX rates + FMC agreements.

Pulls public, no-auth freight data for the Pry platform:

* :func:`get_container_rates` — 40ft container spot rates from the
  Freightos Baltic Index (FBX). The old public ``fbx.freightos.com/api``
  JSON endpoints are retired (they 301 to a marketing page), so the module
  reads the embedded JSON on the public FBX landing page
  (``window.frProductIntroTickerData`` / ``window.frProductIntroChartData``).
  When Freightos is unreachable the module falls back to scraping the
  Drewry World Container Index public Infogram embed.
* :func:`get_fmc_contracts` — agreements on file at the U.S. Federal
  Maritime Commission (FMC) Agreement Library. The FMC publishes no
  official public JSON API, so the module parses the public HTML index.

Contract
--------
* :func:`get_container_rates` — async, never raises, returns a ``list``
  (``[]`` on failure).
* :func:`get_fmc_contracts` — async, never raises, returns a ``list``
  (``[]`` on failure).

Result shapes
-------------
``get_container_rates`` returns a list of::

    {
        "route": "china-us-west-coast",   # slug; "fbx-composite" for the FBX
        "origin": "China",                # aggregate
        "destination": "US West Coast",
        "rate_40ft_usd": 7422.0,          # float or None
        "index_source": "freightos_fbx",  # or "drewry_wci"
        "date": "2026-08-14",             # ISO date
    }

``get_fmc_contracts`` returns a list of::

    {
        "id": "201353-003",               # FMC agreement number
        "carrier": "THE Alliance / Evergreen",
        "shipper": None,                  # FMC does not publish shippers
        "commodity": None,                # nor commodities for agreements
        "origin": "North Europe",         # parsed from agreement name, or None
        "destination": "US East Coast",
        "status": "Active",               # heuristic, see _derive_status
        "effective_date": "2021-03-15",   # ISO date or None
    }

Backoff: 2 retries, exponential (0.4s -> 1.6s).

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
from datetime import date, datetime
from typing import Any

import httpx
from lxml import etree, html as lxml_html

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# ── Public, no-auth sources ────────────────────────────────────────────
# FBX landing page embeds `window.frProductIntroTickerData[...]` (per-lane
# current values, e.g. {"label": "FBX01", "value": "$7,422"}) and
# `window.frProductIntroChartData[...]` (dated numeric series, e.g.
# {"ticker": "FBX", "indexDate": "2026-05-22", "value": 2196.6}).
_FBX_PAGE = (
    "https://www.freightos.com/enterprise/terminal/"
    "freightos-baltic-index-global-container-pricing-index/"
)
# FMC public Agreement Library — server-rendered HTML table, no auth.
_FMC_INDEX = "https://www2.fmc.gov/eagreementssp/public/index"
# Drewry World Container Index — public Infogram embed; chart rows are
# embedded in `window.infographicData = {...}`.
_DREWRY_INFOGRAM = "https://infogram.com/world-container-index-1h17493095xl4zj"

_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-freight/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

_MAX_LIMIT = 50

_FBX_TICKER_RE = re.compile(
    r"window\.frProductIntroTickerData\[\s*['\"][^'\"]+['\"]\s*\]\s*=\s*(\[.*?\]);",
    re.S,
)
_FBX_CHART_RE = re.compile(
    r"window\.frProductIntroChartData\[\s*['\"][^'\"]+['\"]\s*\]\s*=\s*(\[.*?\]);",
    re.S,
)
_DREWRY_DATA_RE = re.compile(r"window\.infographicData\s*=\s*(\{.*?\});", re.S)

# FBX lane table — ticker -> (origin, destination, route slug). FBX01-04 are
# documented in the Freightos API docs; the 11/12/13/14/21/22/24/26 lanes are
# best-effort from the public FBX marketing material. [REVIEW]
_FBX_LANES: dict[str, tuple[str, str, str]] = {
    "FBX": ("Global", "Global", "fbx-composite"),
    "FBX01": ("China", "US West Coast", "china-us-west-coast"),
    "FBX02": ("China", "US East Coast", "china-us-east-coast"),
    "FBX03": ("China", "North Europe", "china-north-europe"),
    "FBX04": ("China", "Mediterranean", "china-mediterranean"),
    "FBX11": ("China", "South America East Coast", "china-south-america-east-coast"),
    "FBX12": ("China", "South America West Coast", "china-south-america-west-coast"),
    "FBX13": ("China", "South Asia", "china-south-asia"),
    "FBX14": ("China", "Middle East", "china-middle-east"),
    "FBX21": ("North Europe", "US East Coast", "north-europe-us-east-coast"),
    "FBX22": ("North Europe", "US West Coast", "north-europe-us-west-coast"),
    "FBX24": ("Mediterranean", "US East Coast", "mediterranean-us-east-coast"),
    "FBX26": ("North Europe", "South America East Coast", "north-europe-south-america-east-coast"),
}

# Drewry WCI series names (as rendered by Infogram) -> route mapping.
_DREWRY_SERIES: dict[str, tuple[str, str, str]] = {
    "Composite": ("Global", "Global", "wci-composite"),
    "Shanghai-Rotterdam": ("Shanghai", "Rotterdam", "shanghai-rotterdam"),
    "Shanghai-Genoa": ("Shanghai", "Genoa", "shanghai-genoa"),
    "Shanghai-Los Angeles": ("Shanghai", "Los Angeles", "shanghai-los-angeles"),
    "Shanghai-New York": ("Shanghai", "New York", "shanghai-new-york"),
    "Rotterdam-New York": ("Rotterdam", "New York", "rotterdam-new-york"),
    "Rotterdam-Shanghai": ("Rotterdam", "Shanghai", "rotterdam-shanghai"),
    "Los Angeles-Shanghai": ("Los Angeles", "Shanghai", "los-angeles-shanghai"),
    "New York-Rotterdam": ("New York", "Rotterdam", "new-york-rotterdam"),
}

# Common route aliases -> set of FBX tickers they cover.
_ROUTE_ALIASES: dict[str, frozenset[str]] = {
    "transpacific": frozenset({"FBX01", "FBX02"}),
    "asia-europe": frozenset({"FBX03", "FBX04"}),
    "transatlantic": frozenset({"FBX21", "FBX22", "FBX24"}),
    "composite": frozenset({"FBX"}),
}

# Agreement-type keywords used to split carrier names from FMC agreement
# names (longest first so "Space Charter Agreement" wins over "Agreement").
_AGREEMENT_KEYWORDS = (
    "Vessel Sharing Agreement",
    "Space Charter Agreement",
    "Cooperative Working Agreement",
    "Joint Service Agreement",
    "Slot Exchange Agreement",
    "Discussion Agreement",
    "Agreement",
)
# Geography hints used to extract trade lanes from FMC agreement names.
_REGION_HINTS: tuple[tuple[str, str], ...] = (
    ("North Europe", "North Europe"),
    ("South America", "South America"),
    ("USEC", "US East Coast"),
    ("US East Coast", "US East Coast"),
    ("East Coast", "East Coast"),
    ("USWC", "US West Coast"),
    ("US West Coast", "US West Coast"),
    ("West Coast", "West Coast"),
    ("Mediterranean", "Mediterranean"),
    ("Middle East", "Middle East"),
    ("Europe", "Europe"),
    ("China", "China"),
    ("Asia", "Asia"),
    ("India", "India"),
    ("Africa", "Africa"),
)


def _slug(text: str) -> str:
    """Lowercase alnum slug (``"US West Coast"`` -> ``"us-west-coast"``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def _parse_money(value: Any) -> float | None:
    """Parse a rate value to float; None for empty/unknown markers."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"n/a", "N/A", "-", "--", "null", "None"}:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_iso_date(value: Any, formats: tuple[str, ...]) -> str | None:
    """Parse a date string to ISO ``YYYY-MM-DD``; None when unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10]):
        return text[:10]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _match_route(record: dict[str, Any], route: str) -> bool:
    """Return True when a rate record matches the requested route filter."""
    query = (route or "").strip().lower()
    if not query or query == "all":
        return True
    record_route = (record.get("route") or "").lower()
    if record_route == query or record_route == f"fbx-{query}" or record_route == f"wci-{query}":
        return True
    # Ticker label filter, e.g. "FBX01".
    if query.upper() in _FBX_LANES and record_route == _FBX_LANES[query.upper()][2]:
        return True
    origin = (record.get("origin") or "").lower()
    destination = (record.get("destination") or "").lower()
    # Transpacific / transatlantic / asia-europe / composite aliases match on
    # the FBX ticker the record came from is handled by the caller; here we
    # accept the alias when it appears in the route/origin/destination text.
    return query in origin or query in destination


async def _fetch_text(url: str, params: dict[str, str] | None = None) -> str | None:
    """GET a URL and return its body text.

    Returns ``None`` on any failure (network, non-2xx, timeout).
    """

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


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


def _infogram_cell(value: Any) -> str:
    """Read a value out of an Infogram cell (dict with ``value`` or raw)."""
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    if value is None:
        return ""
    return str(value).strip()


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


# ── Public: container rates ────────────────────────────────────────────
async def get_container_rates(route: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Return container spot rates for 40ft containers.

    Args:
        route: Route filter — ``"all"`` (default) or a lane: an FBX ticker
            (``"FBX01"``), a route slug (``"china-us-west-coast"``), an
            origin/destination substring (``"china"``), or an alias
            (``"transpacific"``, ``"asia-europe"``, ``"transatlantic"``).
        limit: Max records to return (1-50).

    Returns:
        List of rate records (see module docstring). Freightos FBX is the
        primary source; Drewry WCI is used as a fallback when Freightos
        yields nothing. ``[]`` on total failure. Never raises.
    """
    try:
        return await _get_container_rates(route, limit)
    except Exception:
        logger.exception("freight_rates_crashed", extra={"route": route, "limit": limit})
        return []


async def _get_container_rates(route: str, limit: int) -> list[dict[str, Any]]:
    records = await _fbx_rates(route, limit)
    if not records:
        records = await _drewry_rates(route, limit)
    return records[:limit]


async def _fbx_rates(route: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_FBX_PAGE)
    if text is None:
        return []
    records = _fbx_records_from_page(text)
    return _filter_rate_records(records, route, limit)


async def _drewry_rates(route: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_DREWRY_INFOGRAM)
    if text is None:
        return []
    records = _drewry_records_from_page(text)
    return _filter_rate_records(records, route, limit)


def _filter_rate_records(
    records: list[dict[str, Any]], route: str, limit: int
) -> list[dict[str, Any]]:
    """Apply the route filter + limit to a list of rate records."""
    query = (route or "").strip().lower()
    alias_tickers = _ROUTE_ALIASES.get(query)
    matched: list[dict[str, Any]] = []
    for record in records:
        if alias_tickers is not None:
            # Alias matches FBX tickers; Drewry records never match aliases.
            if record.get("index_source") != "freightos_fbx":
                continue
            ticker = next(
                (label for label in _FBX_LANES if _FBX_LANES[label][2] == record.get("route")),
                None,
            )
            if ticker not in alias_tickers:
                continue
            matched.append(record)
            continue
        if _match_route(record, query):
            matched.append(record)
    matched.sort(key=lambda rec: rec.get("date") or "", reverse=True)
    return matched[: max(1, min(int(limit), _MAX_LIMIT))]


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


def _cell_text(cell: Any) -> str:
    """Stripped text content of an lxml element."""
    return " ".join((cell.text_content() or "").split())


# ── Public: FMC contracts ──────────────────────────────────────────────
async def get_fmc_contracts(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return FMC agreements matching a query.

    Args:
        query: Free-text filter matched against agreement number, carrier,
            origin and destination (case-insensitive substring).
        limit: Max records to return (1-50).

    Returns:
        List of agreement records (see module docstring). The FMC has no
        public JSON API for service contracts (contracts are confidential
        by law), so this reads the public Agreement Library index and maps
        each agreement row to the closest contract-shaped record.
        ``[]`` on failure. Never raises.
    """
    try:
        if not (query or "").strip():
            return []
        return await _get_fmc_contracts(query, limit)
    except Exception:
        logger.exception("fmc_contracts_crashed", extra={"query": query, "limit": limit})
        return []


async def _get_fmc_contracts(query: str, limit: int) -> list[dict[str, Any]]:
    records = await _fetch_fmc_records(query, limit)
    return records[:limit]


async def _fetch_fmc_records(query: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_FMC_INDEX)
    if text is None:
        return []
    records = _parse_fmc_html(text)
    needle = (query or "").strip().lower()
    if needle:
        records = [
            rec
            for rec in records
            if needle in (rec.get("id") or "").lower()
            or needle in (rec.get("carrier") or "").lower()
            or needle in (rec.get("origin") or "").lower()
            or needle in (rec.get("destination") or "").lower()
        ]
    return records[: max(1, min(int(limit), _MAX_LIMIT))]
