"""Optional gridstatus fast-path for ISOs with auth/rate-limit quirks.

gridstatus is NOT a core dependency; when an operator installs it, this
path handles ERCOT / CAISO / PJM day-ahead LMP without per-ISO scraping
hacks. It is never exercised by the tests.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import importlib.util
import logging
from typing import Any

from datasets.energy_data._common import _as_float, _as_text, _iso_utc

logger = logging.getLogger(__name__)


def _gridstatus_available() -> bool:
    """True when the optional ``gridstatus`` library is importable."""
    return importlib.util.find_spec("gridstatus") is not None


async def _fetch_via_gridstatus(region: str, start_date: str) -> list[dict[str, Any]]:
    """Best-effort gridstatus fast-path for ISOs with auth/rate-limit quirks.

    Runs in a thread (gridstatus is sync) and never raises.
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
