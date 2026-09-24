"""NADAC dataset discovery, CSV retrieval, and cache coordination."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import csv
import io
import logging
from typing import Any

import httpx

from datasets.healthcare_data.drug_pricing import config
from pry.engine.retry import async_retry

logger = logging.getLogger(__name__)
_discovery_lock = asyncio.Lock()
_url_lock = asyncio.Lock()
_rows_lock = asyncio.Lock()


async def _fetch_json(url: str, params: dict[str, str] | None = None) -> Any:
    """GET ``url`` and return parsed JSON, or ``None`` on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=config._TIMEOUT, headers=config._JSON_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=config._RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _discover_nadac_datasets_unlocked() -> list[tuple[str, str]]:
    """Return ``(year, uuid)`` NADAC datasets, newest first.

    Starts from the known hardcoded set and refreshes it from the DKAN
    search API so a brand-new year is picked up without a code change.
    """
    datasets = list(config._NADAC_DATASETS)
    payload = await _fetch_json(
        config._SEARCH_URL, {"fulltext": "NADAC Acquisition Cost", "limit": "50"}
    )
    if not isinstance(payload, dict):
        return datasets
    results = payload.get("results")
    if not isinstance(results, dict):
        return datasets
    for item in results.values():
        if not isinstance(item, dict):
            continue
        match = config._DATASET_TITLE_RE.match(str(item.get("title") or ""))
        uuid = item.get("identifier")
        if match and uuid:
            year = match.group(1)
            datasets = [(y, u) for (y, u) in datasets if y != year]
            datasets.append((year, str(uuid)))
    datasets.sort(key=lambda pair: pair[0], reverse=True)
    return datasets


async def _latest_nadac_csv_url_unlocked() -> str | None:
    """Resolve the download URL of the newest NADAC weekly CSV (or None)."""
    cached = config._cache_get(config._NADAC_URL_CACHE, "latest")
    if cached is not None:
        return cached
    found: str | None = None
    for _year, uuid in await _discover_nadac_datasets():
        meta = await _fetch_json(config._METASTORE_URL.format(uuid=uuid))
        if not isinstance(meta, dict):
            continue
        distributions = meta.get("distribution") or []
        for dist in distributions:
            if not isinstance(dist, dict):
                continue
            data = dist.get("data")
            if not isinstance(data, dict):
                continue
            url = data.get("downloadURL")
            if isinstance(url, str) and url.lower().endswith(".csv"):
                found = url
                break
        if found:
            break
    # Negative-cache a miss (24h) so we never hammer the metastore.
    config._cache_set(config._NADAC_URL_CACHE, "latest", found, config._URL_TTL)
    return found


async def _fetch_nadac_rows_unlocked() -> list[dict[str, Any]]:
    """Download + parse the newest NADAC CSV into row dicts (or [])."""
    url = await _latest_nadac_csv_url()
    if not url:
        return []
    cached = config._cache_get(config._NADAC_ROWS_CACHE, url)
    if cached is not None:
        return cached
    rows = await _fetch_csv_rows(url)
    config._cache_set(config._NADAC_ROWS_CACHE, url, rows, config._ROWS_TTL)
    return rows


async def _fetch_csv_rows(url: str) -> list[dict[str, Any]]:
    async def _one() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0), headers=config._JSON_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
        try:
            reader = csv.DictReader(io.StringIO(text))
            return [dict(row) for row in reader]
        except (csv.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"NADAC CSV parse failed: {exc}") from exc

    try:
        return await async_retry(_one, config=config._RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return []


async def _discover_nadac_datasets() -> list[tuple[str, str]]:
    async with _discovery_lock:
        return await _discover_nadac_datasets_unlocked()


async def _latest_nadac_csv_url() -> str | None:
    async with _url_lock:
        return await _latest_nadac_csv_url_unlocked()


async def _fetch_nadac_rows() -> list[dict[str, Any]]:
    async with _rows_lock:
        return await _fetch_nadac_rows_unlocked()
