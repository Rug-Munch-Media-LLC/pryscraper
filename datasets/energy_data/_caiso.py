"""CAISO real-time 5-minute LMP — keyless OASIS ``SingleZip`` report.

Honest flag: OASIS has its own availability windows and rate limits, and
an ``ALL_APNODES`` query is heavy — treat as best-effort.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta
from typing import Any

import httpx

from datasets.energy_data._common import _HEADERS, _TIMEOUT, _as_float, _as_text, _iso_utc

logger = logging.getLogger(__name__)

_CAISO_OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"


def _parse_caiso_csv(text: str) -> list[dict[str, Any]]:
    """Parse a CAISO OASIS PRC_INTVL_LMP CSV into canonical LMP records.

    Best-effort column names: ``INTERVALSTARTTIME``, ``NODE_ID``/``PNODE_ID``,
    ``LMP_PRICE``.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except (csv.Error, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for row in rows:
        node = (
            _as_text(row.get("NODE_ID"))
            or _as_text(row.get("PNODE_ID"))
            or _as_text(row.get("node"))
        )
        ts = _as_text(row.get("INTERVALSTARTTIME")) or _as_text(row.get("timestamp"))
        price = _as_float(row.get("LMP_PRICE") or row.get("lmp"))
        if not node or not ts or price is None:
            continue
        records.append(
            {
                "region": "caiso",
                "node": node,
                "timestamp": _iso_utc(ts),
                "price_usd_mwh": price,
                "lmp_type": "RTM",
            }
        )
    return records


async def _fetch_caiso(start_date: str) -> list[dict[str, Any]]:
    """Fetch CAISO real-time 5-minute LMP via the OASIS API (keyless).

    OASIS ``SingleZip`` returns a ZIP archive containing CSVs; we unpack the
    first CSV and parse it.
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d")
    except ValueError:
        return []
    end_dt = start_dt + timedelta(days=1)
    params = {
        "queryname": "PRC_INTVL_LMP",
        "startdatetime": start_dt.strftime("%Y%m%dT00:00-0000"),
        "enddatetime": end_dt.strftime("%Y%m%dT00:00-0000"),
        "version": "3",
        "market_run_id": "RTM",
        "grp_type": "ALL_APNODES",
    }
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_CAISO_OASIS_URL, params=params)
            response.raise_for_status()
            content = response.content
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("caiso_fetch_failed", extra={"error": str(exc)[:120]})
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                return []
            text = archive.read(csv_names[0]).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, ValueError):
        return []
    return _parse_caiso_csv(text)
