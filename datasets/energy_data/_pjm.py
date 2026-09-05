"""PJM day-ahead hourly LMP — Data Miner 2 feed (free API key required).

Without ``PRY_PJM_API_KEY`` the feed returns an HTML login page, so the
fetcher short-circuits to ``[]`` rather than scrape garbage.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import csv
import io
import json
import logging
import os
from typing import Any

import httpx

from datasets.energy_data._common import _HEADERS, _TIMEOUT, _as_float, _as_text, _iso_utc

logger = logging.getLogger(__name__)

_PJM_FEED = "https://dataminer2.pjm.com/feed/da_hrl_lmps"


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
    """Fetch PJM day-ahead hourly LMP via Data Miner 2 (needs a free key)."""
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
