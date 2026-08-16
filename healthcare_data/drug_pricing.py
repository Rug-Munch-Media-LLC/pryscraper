"""Drug pricing — NADAC public files + best-effort GoodRx consumer price.

Two free sources are aggregated here, both US-market drug pricing:

* **NADAC** (National Average Drug Acquisition Cost) — published weekly by
  CMS on ``data.medicaid.gov`` (public-domain, no auth). The module locates
  the newest yearly dataset via the DKAN metastore API, resolves its weekly
  CSV download URL, and filters rows by drug description. This is the
  primary source.
* **GoodRx** — consumer retail-price pages (``goodrx.com/{drug-slug}``).
  Used only as a fallback when NADAC has no match. GoodRx pages are heavily
  JS-gated (Cloudflare/captcha), so this path frequently degrades to
  ``None``; that is expected and documented — never an exception.

Contract
--------
* :func:`get_drug_price` — async, never raises, returns a ``dict`` (``{}``
  on failure). Accepts a drug name (brand or generic), e.g. ``"atorvastatin"``
  or ``"Lipitor"``.

Result shape
------------
``get_drug_price`` returns:

    {
        "drug": "ATORVASTATIN CALCIUM 10 MG",
        "ndc": "00093072098",
        "price_per_unit": 0.02633,
        "price_type": "NADAC per EA",
        "source": "nadac",
        "effective_date": "2025-12-24",
        "pricing_unit": "EA",
        "otc": "N",
    }

When only GoodRx data is available the shape is
``{"drug": ..., "ndc": None, "price_per_unit": ..., "price_type":
"goodrx_retail", "source": "goodrx", "url": ...}``.

NADAC dataset terms: https://data.medicaid.gov (public-domain). Backoff:
2 retries, exponential (0.4s -> 1.6s). Dataset/CSV discovery is cached
in-process (24h), parsed CSV rows for 6h.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from datetime import date, datetime
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://data.medicaid.gov/api/1/search"
_METASTORE_URL = (
    "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items/{uuid}"
    "?show-reference-ids=false"
)
_GOODRX_URL = "https://www.goodrx.com/{slug}"

_TIMEOUT = httpx.Timeout(25.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_JSON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-healthcare/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# NADAC is split into per-calendar-year datasets. Newest first so the
# runtime resolves the most recent weekly file. The DKAN search API is also
# probed once (cached 24h) so a new year is picked up automatically.
_NADAC_DATASETS: tuple[tuple[str, str], ...] = (
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

_URL_TTL = 24 * 60 * 60  # dataset discovery + CSV url
_ROWS_TTL = 6 * 60 * 60  # parsed CSV rows

_JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


# ── tiny in-process TTL cache ─────────────────────────────────────────
_NADAC_URL_CACHE: dict[str, Any] = {}
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


# ── helpers ───────────────────────────────────────────────────────────
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
        pass
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


# ── NADAC discovery ────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> Any:
    """GET ``url`` and return parsed JSON, or ``None`` on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_JSON_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _discover_nadac_datasets() -> list[tuple[str, str]]:
    """Return ``(year, uuid)`` NADAC datasets, newest first.

    Starts from the known hardcoded set and refreshes it from the DKAN
    search API so a brand-new year is picked up without a code change.
    """
    datasets = list(_NADAC_DATASETS)
    payload = await _fetch_json(_SEARCH_URL, {"fulltext": "NADAC Acquisition Cost", "limit": "50"})
    if not isinstance(payload, dict):
        return datasets
    results = payload.get("results")
    if not isinstance(results, dict):
        return datasets
    for item in results.values():
        if not isinstance(item, dict):
            continue
        match = _DATASET_TITLE_RE.match(str(item.get("title") or ""))
        uuid = item.get("identifier")
        if match and uuid:
            year = match.group(1)
            datasets = [(y, u) for (y, u) in datasets if y != year]
            datasets.append((year, str(uuid)))
    datasets.sort(key=lambda pair: pair[0], reverse=True)
    return datasets


async def _latest_nadac_csv_url() -> str | None:
    """Resolve the download URL of the newest NADAC weekly CSV (or None)."""
    cached = _cache_get(_NADAC_URL_CACHE, "latest")
    if cached is not None:
        return cached
    found: str | None = None
    for _year, uuid in await _discover_nadac_datasets():
        meta = await _fetch_json(_METASTORE_URL.format(uuid=uuid))
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
    _cache_set(_NADAC_URL_CACHE, "latest", found, _URL_TTL)
    return found


async def _fetch_nadac_rows() -> list[dict[str, Any]]:
    """Download + parse the newest NADAC CSV into row dicts (or [])."""
    url = await _latest_nadac_csv_url()
    if not url:
        return []
    cached = _cache_get(_NADAC_ROWS_CACHE, url)
    if cached is not None:
        return cached
    rows = await _fetch_csv_rows(url)
    _cache_set(_NADAC_ROWS_CACHE, url, rows, _ROWS_TTL)
    return rows


async def _fetch_csv_rows(url: str) -> list[dict[str, Any]]:
    async def _one() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0), headers=_JSON_HEADERS, follow_redirects=True
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
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return []


# ── GoodRx fallback ────────────────────────────────────────────────────
def _goodrx_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "drugs"


def _parse_goodrx_price(html: str) -> float | None:
    """Extract a consumer retail price from GoodRx JSON-LD (or None)."""
    for match in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict) or str(node.get("@type") or "").lower() != "product":
                continue
            offers = node.get("offers")
            candidates: list[Any] = []
            if isinstance(offers, dict):
                candidates = [offers.get("price"), offers.get("lowPrice"), offers.get("highPrice")]
            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        candidates.extend([offer.get("price"), offer.get("lowPrice")])
            for price in candidates:
                parsed = _as_float(price)
                if parsed is not None:
                    return parsed
    return None


async def _try_goodrx(name: str) -> dict[str, Any] | None:
    """Best-effort GoodRx retail price. Returns None when gated/unavailable."""
    slug = _goodrx_slug(name)
    url = _GOODRX_URL.format(slug=slug)

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        price = _parse_goodrx_price(html)
        if price is None:
            raise ValueError("no parseable GoodRx price in page")
        return {
            "drug": name,
            "ndc": None,
            "price_per_unit": price,
            "price_type": "goodrx_retail",
            "source": "goodrx",
            "url": url,
        }

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_drug_price(drug_name: str) -> dict[str, Any]:
    """Look up a US drug price by name (brand or generic).

    Args:
        drug_name: e.g. ``"atorvastatin"``, ``"Lipitor"``.

    Returns:
        Price record (see module docstring) or ``{}`` when no free source
        matched (unknown drug, network failure). Never raises.
    """
    try:
        return await _get_drug_price(drug_name)
    except Exception:
        logger.exception("health_drug_price_crashed", extra={"drug": drug_name})
        return {}


async def _get_drug_price(drug_name: str) -> dict[str, Any]:
    name = str(drug_name or "").strip()
    if not name:
        logger.warning("health_drug_price_empty")
        return {}
    needle = name.upper()
    rows = await _fetch_nadac_rows()
    candidates = [row for row in rows if needle in str(row.get("NDC Description") or "").upper()]
    if candidates:
        record = _best_nadac_record(candidates, name)
        if record:
            return record
    # NADAC miss → best-effort GoodRx consumer-price scrape (often gated).
    goodrx = await _try_goodrx(name)
    if goodrx:
        return goodrx
    return {}
