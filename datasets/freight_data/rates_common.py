"""Shared constants + helpers for the freight rates collectors.

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
import re
from datetime import datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

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


def _infogram_cell(value: Any) -> str:
    """Read a value out of an Infogram cell (dict with ``value`` or raw)."""
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def _cell_text(cell: Any) -> str:
    """Stripped text content of an lxml element."""
    return " ".join((cell.text_content() or "").split())
