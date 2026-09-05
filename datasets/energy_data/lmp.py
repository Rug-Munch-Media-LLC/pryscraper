"""ISO day-ahead LMP + EIA fuel prices — free public energy markets data.

Backed by five free sources:

* **NYISO MIS public archive** — day-ahead zonal LBMP CSV at
  ``https://mis.nyiso.com/public/csv/damlbmp/{yyyymmdd}damlbmp_zone.csv``.
  No key, no anti-bot; verified live 2026-08-16. This is the primary
  keyless source and the one exercised by the test-suite mocks.
* **PJM Data Miner 2** — ``da_hrl_lmps`` day-ahead hourly LMP feed. The
  REST feed requires a free PJM API key (``PRY_PJM_API_KEY``); without a
  key it returns an HTML login page, so it degrades to ``[]``.
* **ERCOT public dashboard (keyless)** — real-time system-wide price feed
  at ``https://www.ercot.com/api/1/services/read/dashboards/systemWidePrices.json``
  (``rtSppData[].hbBusAvg``, ~15-min cadence). No key, no auth — but it is
  an *unofficial* dashboard endpoint that ERCOT can change or block at any
  time, and it only exposes a system-wide hub-bus average (not nodal LMPs)
  for the current time window (the requested ``date`` is best-effort).
  Honest flag: treat ERCOT as real-time, system-level, best-effort.
* **CAISO OASIS API (keyless)** — ``SingleZip?queryname=PRC_INTVL_LMP``
  real-time 5-minute LMP report (``market_run_id=RTM``, ``grp_type=ALL_APNODES``).
  No key for basic queries; OASIS returns a ZIP of CSVs. Honest flag: the
  OASIS service has its own availability windows and rate limits, and an
  ALL_APNODES query is heavy — treat as best-effort.
* **gridstatus (optional)** — when the ``gridstatus`` library is
  installed it is used as a fast-path for PJM / ERCOT / CAISO (those ISOs
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
- ERCOT dashboard: https://www.ercot.com/ — keyless, unofficial, may change.
- CAISO OASIS: https://oasis.caiso.com/ — keyless basic queries, rate-limited.
- EIA v2: https://www.eia.gov/opendata/ — free API key, generous limits.

This module is the orchestrator / public API; per-ISO fetchers live in
``_nyiso`` / ``_pjm`` / ``_ercot`` / ``_caiso`` / ``_gridstatus`` / ``_eia``
and shared plumbing in ``_common``.

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
import os
from typing import Any

import httpx

from datasets.energy_data._caiso import _fetch_caiso
from datasets.energy_data._common import _HEADERS, _TIMEOUT, _normalize_date, _normalize_region
from datasets.energy_data._eia import _fetch_eia_area, _fuel_areas
from datasets.energy_data._ercot import _fetch_ercot
from datasets.energy_data._gridstatus import _fetch_via_gridstatus, _gridstatus_available
from datasets.energy_data._nyiso import _fetch_nyiso
from datasets.energy_data._pjm import _fetch_pjm
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)


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
            results.extend(await _fetch_nyiso(start, _get_csv_text))
        elif name == "ercot":
            # Keyless direct feed first; gridstatus is a fallback when the
            # unofficial dashboard is down or the operator installed it.
            direct = await _fetch_ercot(start)
            if direct:
                results.extend(direct)
            elif has_gridstatus:
                results.extend(await _fetch_via_gridstatus(name, start))
        elif name == "caiso":
            direct = await _fetch_caiso(start)
            if direct:
                results.extend(direct)
            elif has_gridstatus:
                results.extend(await _fetch_via_gridstatus(name, start))
        elif has_gridstatus:
            results.extend(await _fetch_via_gridstatus(name, start))
        elif name == "pjm":
            results.extend(await _fetch_pjm(start))
        # ercot/caiso have direct keyless fetchers; gridstatus (when
        # installed) is used as a fallback above.
    return results


# ── Public API: EIA fuel prices ───────────────────────────────────────


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
        records.extend(await _fetch_eia_area(area, api_key, _RETRY_CONFIG))
    return records
