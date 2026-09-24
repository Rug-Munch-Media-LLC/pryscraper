"""Drug-pricing constants, cache primitives, and normalization helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig

logger = logging.getLogger(__name__)
_SEARCH_URL = "https://data.medicaid.gov/api/1/search"
_METASTORE_URL = "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items/{uuid}?show-reference-ids=false"
_GOODRX_URL = "https://www.goodrx.com/{slug}"
_TIMEOUT = httpx.Timeout(25.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2, base_delay=0.4, max_delay=1.6, retryable_exceptions=(httpx.HTTPError,)
)
_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-healthcare/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
_NADAC_DATASETS = (
    ("2025", "f38d0706-1239-442c-a3cc-40ef1b686ac0"),
    ("2024", "99315a95-37ac-4eee-946a-3c523b4c481e"),
    ("2023", "4a00010a-132b-4e4d-a611-543c9521280f"),
    ("2020", "c933dc16-7de9-52b6-8971-4b75992673e0"),
    ("2019", "76a1984a-6d69-5e4d-86c8-65eb31f0506d"),
    ("2018", "8de1b213-73c5-552b-b84e-ac795f34d056"),
    ("2017", "1c5d0fc9-693a-534a-8240-4627d9362b0d"),
    ("2016", "7656fc17-f1b4-566b-9a2d-c4a4f2ac7ae1"),
    ("2015", "4d7af295-2132-55a8-b40c-d6630061f3e8"),
    ("2014", "ba0c3734-8012-549a-8f50-2ff389d0e0ef"),
    ("2013", "1fe73992-cbfd-5109-97bc-dee8b33fdcff"),
)
_DATASET_TITLE_RE = re.compile(r"NADAC \(National Average Drug Acquisition Cost\) (\d{4})")
_URL_TTL = 24 * 60 * 60
_ROWS_TTL = 6 * 60 * 60
_NADAC_URL_CACHE: dict[str, Any] = {}
_NADAC_ROWS_CACHE: dict[str, Any] = {}

_JSON_LD_RE = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)
_NADAC_ROWS_CACHE: dict[str, Any] = {}


def _cache_get(store: dict[str, Any], key: str) -> Any | None:
    entry = store.get(key)
    if entry is None:
        return None
    value, expires = entry
    if expires > time.monotonic():
        return value
    store.pop(key, None)
    return None


def _cache_set(store: dict[str, Any], key: str, value: Any, ttl: float) -> None:
    store[key] = (value, time.monotonic() + ttl)


def _clear_caches() -> None:
    """Drop all in-process NADAC caches (tests and manual refresh)."""
    _NADAC_URL_CACHE.clear()
    _NADAC_ROWS_CACHE.clear()


def _as_float(value: Any) -> float | None:
    """Parse a CSV numeric cell to float (None on failure)."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_effective_date(value: Any) -> date | None:
    """Parse an NADAC ``MM/DD/YYYY`` effective-date cell."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text)  # already ISO (defensive)
    except ValueError:
        pass  # try human formats below
    for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _best_nadac_record(candidates: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Pick the most relevant NADAC row and map it onto the record shape."""
    priced = [row for row in candidates if _as_float(row.get("NADAC Per Unit")) is not None]
    pool = priced or candidates
    if not pool:
        return None
    # Stable sorts: NDC ascending first, then most-recent effective date
    # first — so ties resolve to the lowest NDC.
    pool.sort(key=lambda row: str(row.get("NDC") or ""))
    pool.sort(
        key=lambda row: _parse_effective_date(row.get("Effective Date")) or date.min, reverse=True
    )
    best = pool[0]

    description = str(best.get("NDC Description") or name)
    price = _as_float(best.get("NADAC Per Unit"))
    pricing_unit = str(best.get("Pricing Unit") or "").strip() or None
    effective = _parse_effective_date(best.get("Effective Date"))
    record: dict[str, Any] = {
        "drug": description,
        "ndc": str(best.get("NDC") or "").strip() or None,
        "price_per_unit": price,
        "price_type": f"NADAC per {pricing_unit}" if pricing_unit else "NADAC per unit",
        "source": "nadac",
    }
    if effective is not None:
        record["effective_date"] = effective.isoformat()
    if pricing_unit:
        record["pricing_unit"] = pricing_unit
    if _as_text(best.get("OTC")):
        record["otc"] = _as_text(best.get("OTC"))
    return record


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
