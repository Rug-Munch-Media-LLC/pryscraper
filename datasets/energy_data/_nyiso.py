"""NYISO day-ahead zonal LBMP — keyless MIS public archive CSV.

Primary keyless LMP source; exercised by the test-suite mocks.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from datetime import datetime, timedelta

from datasets.energy_data._common import _as_float, _as_text, _nyiso_ts_to_utc

_NYISO_BASE = "https://mis.nyiso.com/public/csv/damlbmp"

# Day-ahead LMP is published the evening before the trading day; when the
# requested date's file is not out yet, step back up to this many days.
_LMP_RETRY_DAYS = 3


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


async def _fetch_nyiso(start_date: str, get_csv_text: Callable[[str], Any]) -> list[dict[str, Any]]:
    """Fetch NYISO day-ahead zonal LBMP, stepping back up to N days.

    The DAM file for a trading day is published the prior evening; if the
    requested date is not out yet we step back one calendar day at a time.
    ``get_csv_text`` is the retrying HTTP text fetcher injected by the
    orchestrator (so its retry config stays patchable in one place).
    """
    for offset in range(_LMP_RETRY_DAYS + 1):
        candidate = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=offset)).strftime(
            "%Y%m%d"
        )
        text = await get_csv_text(f"{_NYISO_BASE}/{candidate}damlbmp_zone.csv")
        if not text:
            continue
        records = _parse_nyiso_csv(text)
        if records:
            return records
    return []
