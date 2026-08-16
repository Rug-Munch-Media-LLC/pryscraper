"""ISO day-ahead LMP + EIA fuel prices — free public energy markets data.

Backed by three free sources:

* **NYISO MIS public archive** — day-ahead zonal LBMP CSV at
  ``https://mis.nyiso.com/public/csv/damlbmp/{yyyymmdd}damlbmp_zone.csv``.
  No key, no anti-bot; verified live 2026-08-16. This is the primary
  keyless source and the one exercised by the test-suite mocks.
* **PJM Data Miner 2** — ``da_hrl_lmps`` day-ahead hourly LMP feed. The
  REST feed requires a free PJM API key (``PRY_PJM_API_KEY``); without a
  key it returns an HTML login page, so it degrades to ``[]``.
* **gridstatus (optional)** — when the ``gridstatus`` library is
  installed it is used as a fast-path for ERCOT / CAISO / PJM (those ISOs
  have cookie / auth / rate-limit quirks that gridstatus handles). It is
  NOT a core dependency and is never exercised by the tests.

Contract
--------
* :func:`get_lmp` — async, never raises, returns a ``list`` (``[]`` on
  failure). ISO day-ahead locational marginal prices.
* :func:`get_fuel_prices` — async, never raises, returns a ``list``
  (``[]`` on failure). Weekly retail fuel prices via the EIA v2 API
  (``PRY_EIA_API_KEY``; free registration at
  https://www.eia.gov/opendata/register.php).

Result shapes
-------------
``get_lmp`` records::

    {"region": "nyiso", "node": "CAPITL", "timestamp": "2026-08-15T04:00:00+00:00",
     "price_usd_mwh": 42.97, "lmp_type": "DAM"}

``get_fuel_prices`` records::

    {"region": "us", "fuel": "gasoline", "price": 4.141,
     "unit": "$/GAL", "date": "2026-08-10"}

Free-API terms:
- NYISO MIS: https://www.nyiso.com/ — anonymous CSV archive, no rate limit.
- PJM Data Miner 2: https://dataminer2.pjm.com/ — free API key.
- EIA v2: https://www.eia.gov/opendata/ — free API key, generous limits.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import csv
import importlib.util
import io
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_NYISO_BASE = "https://mis.nyiso.com/public/csv/damlbmp"
_PJM_FEED = "https://dataminer2.pjm.com/feed/da_hrl_lmps"
_EIA_BASE = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-energy/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "text/csv, application/json, */*",
}

# NYISO timestamps are ET wall-clock; convert via America/New_York when the
# host has tzdata, else degrade to naive ISO (never crash at import time).
_ET: ZoneInfo | None
try:
    _ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # pragma: no cover - tzdata-less hosts
    _ET = None

# Day-ahead LMP is published the evening before the trading day; when the
# requested date's file is not out yet, step back up to this many days.
_LMP_RETRY_DAYS = 3

_ALL_REGIONS = ("nyiso", "pjm", "ercot", "caiso")
_REGION_ALIASES = {
    "nyiso": "nyiso",
    "new york": "nyiso",
    "pjm": "pjm",
    "ercot": "ercot",
    "texas": "ercot",
    "caiso": "caiso",
    "california": "caiso",
}

# EIA v2 `pri/gnd` area facet codes (weekly retail gasoline/diesel prices).
_EIA_AREA_BY_REGION = {
    "us": "NUS",
    "padd1": "R10",
    "padd2": "R20",
    "padd3": "R30",
    "padd4": "R40",
    "padd5": "R50",
}
_EIA_ALL_AREAS = ("NUS", "R10", "R20", "R30", "R40", "R50")
# (product facet code, canonical fuel label)
_EIA_PRODUCTS = (
    ("EPM0", "gasoline"),
    ("EPD0", "premium gasoline"),
    ("EDI0", "diesel"),
)
_MAX_FUEL_ROWS = 60


# ── value coercers ────────────────────────────────────────────────────


def _as_text(value: Any) -> str | None:
    """Coerce a JSON/CSV value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    """Coerce a JSON/CSV value to float/None ('' -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nyiso_ts_to_utc(value: str) -> str:
    """Convert NYISO's ET wall-clock timestamp to ISO-8601 UTC.

    NYISO files carry naive Eastern Time (no DST marker); the zoneinfo
    conversion is DST-aware. Falls back to the raw value when the host has
    no tzdata (``_ET is None``).
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        local = datetime.strptime(text, "%m/%d/%Y %H:%M")
    except ValueError:
        return text
    if _ET is None:
        return local.isoformat()
    try:
        return local.replace(tzinfo=_ET).astimezone(UTC).isoformat()
    except (ValueError, OverflowError):  # pragma: no cover - defensive, never raise
        return local.isoformat()


def _iso_utc(value: str) -> str:
    """Normalize a (possibly naive) ISO-8601 string to ISO-8601 UTC."""
    text = (value or "").strip().replace("Z", "+00:00")
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


# ── region / date normalization ───────────────────────────────────────


def _normalize_region(region: str) -> list[str]:
    """Resolve a region name to the ISO list to fetch ([] = unknown)."""
    text = (region or "").strip().lower()
    if not text:
        return []
    if text == "all":
        return list(_ALL_REGIONS)
    if text in _REGION_ALIASES:
        return [_REGION_ALIASES[text]]
    return []


def _normalize_date(date: str) -> str | None:
    """Return 'YYYYMMDD' for 'today' / 'YYYY-MM-DD' / 'YYYYMMDD', else None."""
    text = (date or "").strip().lower()
    if not text:
        return None
    if text == "today":
        return datetime.now(UTC).date().strftime("%Y%m%d")
    compact = text.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return compact
    return None


# ── HTTP helpers ──────────────────────────────────────────────────────


async def _get_csv_text(url: str) -> str | None:
    """GET ``url`` and return its text, or None on any HTTP/OSError."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


# ── NYISO day-ahead LMP ───────────────────────────────────────────────


def _parse_nyiso_csv(text: str) -> list[dict[str, Any]]:
    """Parse NYISO DAM LBMP CSV rows into canonical LMP records.

    Columns: ``Time Stamp`` (ET), ``Name`` (zone), ``PTID``,
    ``LBMP ($/MWHr)``, ``Marginal Cost Losses ($/MWHr)``,
    ``Marginal Cost Congestion ($/MWHr)``.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except (csv.Error, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for row in rows:
        ts = _as_text(row.get("Time Stamp"))
        node = _as_text(row.get("Name"))
        price = _as_float(row.get("LBMP ($/MWHr)"))
        if not ts or not node or price is None:
            continue
        records.append(
            {
                "region": "nyiso",
                "node": node,
                "timestamp": _nyiso_ts_to_utc(ts),
                "price_usd_mwh": price,
                "lmp_type": "DAM",
            }
        )
    return records


async def _fetch_nyiso(start_date: str) -> list[dict[str, Any]]:
    """Fetch NYISO day-ahead zonal LBMP, stepping back up to N days.

    The DAM file for a trading day is published the prior evening; if the
    requested date is not out yet we step back one calendar day at a time.
    """
    for offset in range(_LMP_RETRY_DAYS + 1):
        candidate = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=offset)).strftime(
            "%Y%m%d"
        )
        text = await _get_csv_text(f"{_NYISO_BASE}/{candidate}damlbmp_zone.csv")
        if not text:
            continue
        records = _parse_nyiso_csv(text)
        if records:
            return records
    return []


# ── PJM day-ahead LMP ─────────────────────────────────────────────────


def _parse_pjm_payload(text: str) -> list[dict[str, Any]]:
    """Parse a PJM Data Miner 2 response (JSON or CSV) into LMP records.

    Data Miner 2 returns JSON by default and CSV when ``download=true``;
    both are parsed defensively. Best-effort column names: node_id/pnode_id,
    datetime_beginning_utc, marginal_cost_lmp.
    """
    rows: list[dict[str, Any]] = []
    payload: Any = None
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("items", "rows", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = [r for r in candidate if isinstance(r, dict)]
                break
    elif isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    else:
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except (csv.Error, ValueError):
            rows = []
    records: list[dict[str, Any]] = []
    for row in rows:
        node = (
            _as_text(row.get("node_id"))
            or _as_text(row.get("pnode_id"))
            or _as_text(row.get("node"))
        )
        ts = _as_text(row.get("datetime_beginning_utc")) or _as_text(row.get("timestamp"))
        price = _as_float(row.get("marginal_cost_lmp") or row.get("lmp") or row.get("total_lmp"))
        if not node or not ts or price is None:
            continue
        records.append(
            {
                "region": "pjm",
                "node": node,
                "timestamp": _iso_utc(ts),
                "price_usd_mwh": price,
                "lmp_type": _as_text(row.get("type")) or "DAM",
            }
        )
    return records


async def _fetch_pjm(start_date: str) -> list[dict[str, Any]]:
    """Fetch PJM day-ahead hourly LMP via Data Miner 2 (needs a free key).

    Without ``PRY_PJM_API_KEY`` the feed returns an HTML login page, so we
    short-circuit to ``[]`` rather than scrape garbage.
    """
    api_key = (os.getenv("PRY_PJM_API_KEY") or "").strip()
    if not api_key:
        logger.info("energy_pjm_skipped_no_api_key")
        return []
    headers = {**_HEADERS, "Accept": "text/csv, application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=headers, follow_redirects=True
        ) as client:
            response = await client.get(
                f"{_PJM_FEED}/{start_date}", params={"apikey": api_key, "download": "true"}
            )
            response.raise_for_status()
            text = response.text
    except (httpx.HTTPError, OSError):
        return []
    return _parse_pjm_payload(text)


# ── gridstatus fast-path (optional) ───────────────────────────────────


def _gridstatus_available() -> bool:
    """True when the optional ``gridstatus`` library is importable."""
    return importlib.util.find_spec("gridstatus") is not None


async def _fetch_via_gridstatus(region: str, start_date: str) -> list[dict[str, Any]]:
    """Best-effort gridstatus fast-path for ISOs with auth/rate-limit quirks.

    gridstatus is NOT a core dependency; when an operator installs it, this
    path handles ERCOT / CAISO / PJM day-ahead LMP without per-ISO scraping
    hacks. Runs in a thread (gridstatus is sync) and never raises.
    """
    try:
        import gridstatus  # type: ignore[import-not-found]

        iso_cls = getattr(gridstatus, region.upper(), None)
        if iso_cls is None:
            return []
        iso = iso_cls()
        frame = await asyncio.to_thread(
            iso.get_lmp, date=start_date, end=start_date, market="DAY_AHEAD"
        )
    except Exception:
        logger.exception("energy_gridstatus_failed", extra={"region": region})
        return []
    if frame is None or getattr(frame, "empty", True):
        return []
    try:
        if not {"Interval Start Time", "Location", "LMP"}.issubset(frame.columns):
            return []
        records: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            raw_ts = row["Interval Start Time"]
            ts = raw_ts.isoformat() if hasattr(raw_ts, "isoformat") else str(raw_ts)
            node = _as_text(row["Location"])
            price = _as_float(row["LMP"])
            if not node or price is None:
                continue
            records.append(
                {
                    "region": region,
                    "node": node,
                    "timestamp": _iso_utc(ts),
                    "price_usd_mwh": price,
                    "lmp_type": "DAM",
                }
            )
        return records
    except Exception:
        logger.exception("energy_gridstatus_mapping_failed", extra={"region": region})
        return []


# ── Public API: LMP ───────────────────────────────────────────────────


async def get_lmp(region: str = "all", date: str = "today") -> list[dict[str, Any]]:
    """Return ISO day-ahead locational marginal prices.

    Args:
        region: ISO name — ``"nyiso"``, ``"pjm"``, ``"ercot"``,
            ``"caiso"`` — or ``"all"``.
        date: ``"today"`` or ``"YYYY-MM-DD"`` (the trading day; steps back
            up to 3 days when that day's file is not published yet).

    Returns:
        List of LMP records (see module docstring). ``[]`` on failure.
        Never raises.
    """
    try:
        return await _get_lmp(region, date)
    except Exception:
        logger.exception("energy_lmp_crashed", extra={"region": region, "date": date})
        return []


async def _get_lmp(region: str, date: str) -> list[dict[str, Any]]:
    wanted = _normalize_region(region)
    if not wanted:
        return []
    start = _normalize_date(date)
    if not start:
        return []

    has_gridstatus = _gridstatus_available()
    results: list[dict[str, Any]] = []
    for name in wanted:
        if name == "nyiso":
            results.extend(await _fetch_nyiso(start))
        elif has_gridstatus:
            results.extend(await _fetch_via_gridstatus(name, start))
        elif name == "pjm":
            results.extend(await _fetch_pjm(start))
        # ercot / caiso without gridstatus -> no keyless direct fetcher yet
    return results


# ── EIA fuel prices ───────────────────────────────────────────────────


def _fuel_areas(region: str) -> list[str]:
    """Resolve a fuel-price region to EIA duoarea facet codes ([] = unknown)."""
    text = (region or "").strip().lower()
    if not text:
        return []
    if text == "all":
        return list(_EIA_ALL_AREAS)
    if text in _EIA_AREA_BY_REGION:
        return [_EIA_AREA_BY_REGION[text]]
    return []


def _area_label(area: str) -> str:
    """Map an EIA duoarea code back to the canonical region label."""
    for label, code in _EIA_AREA_BY_REGION.items():
        if code == area:
            return label
    return area.lower()


def _parse_eia_payload(area: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one EIA v2 response into fuel-price records.

    Rows are sorted newest-first by period; keep the latest period per
    product facet code.
    """
    rows = payload.get("response", {}).get("data")
    if not isinstance(rows, list):
        return []
    latest_by_product: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        product = _as_text(row.get("product"))
        if not product or product in latest_by_product:
            continue
        latest_by_product[product] = row
    records: list[dict[str, Any]] = []
    for product_code, fuel in _EIA_PRODUCTS:
        row = latest_by_product.get(product_code)
        if not row:
            continue
        price = _as_float(row.get("value"))
        date = _as_text(row.get("period"))
        if price is None or not date:
            continue
        records.append(
            {
                "region": _area_label(area),
                "fuel": fuel,
                "price": price,
                "unit": _as_text(row.get("units")) or "$/GAL",
                "date": date,
            }
        )
    return records


async def _fetch_eia_area(area: str, api_key: str) -> list[dict[str, Any]]:
    """Fetch the latest weekly gasoline/diesel prices for one EIA area."""
    params: dict[str, str] = {
        "frequency": "weekly",
        "data[0]": "value",
        "facets[process][]": "PTE",
        "facets[duoarea][]": area,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": str(_MAX_FUEL_ROWS),
        "api_key": api_key,
    }

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_EIA_BASE, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("EIA payload is not an object")
        return payload

    try:
        payload = await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    return _parse_eia_payload(area, payload)


async def get_fuel_prices(region: str = "all") -> list[dict[str, Any]]:
    """Return weekly retail fuel prices (gasoline / diesel) from EIA v2.

    Args:
        region: ``"us"``, ``"padd1"``..``"padd5"``, or ``"all"`` (the U.S.
            plus all five PADD districts).

    Returns:
        List of fuel-price records (see module docstring). ``[]`` on
        failure (e.g. missing ``PRY_EIA_API_KEY``). Never raises.
    """
    try:
        return await _get_fuel_prices(region)
    except Exception:
        logger.exception("energy_fuel_prices_crashed", extra={"region": region})
        return []


async def _get_fuel_prices(region: str) -> list[dict[str, Any]]:
    api_key = (os.getenv("PRY_EIA_API_KEY") or "").strip()
    if not api_key:
        logger.info("energy_eia_skipped_no_api_key")
        return []
    areas = _fuel_areas(region)
    if not areas:
        return []
    records: list[dict[str, Any]] = []
    for area in areas:
        records.extend(await _fetch_eia_area(area, api_key))
    return records
