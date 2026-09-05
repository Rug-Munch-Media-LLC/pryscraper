"""Shared helpers and constants for the grocery price sources.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import html
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")

_EXCLUDED_EXCEPTIONS = (
    httpx.HTTPError,
    OSError,
    json.JSONDecodeError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    re.error,
)


def _valid_zip(zip_code: str) -> bool:
    return bool(_ZIP_RE.fullmatch(zip_code.strip()))


def _clean_name(value: Any) -> str:
    """Collapse whitespace / HTML entities in a product name; '' if unusable."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return cleaned[:200]


def _safe_float(value: Any) -> float | None:
    """Parse a price from a number or a ``$9.99``-style string; None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return round(float(match.group(0)), 2)
    except ValueError:
        return None


def _extract_price(price_info: Any) -> float | None:
    """Best price from a Kroger/Walmart ``price`` object or bare number."""
    if isinstance(price_info, (int, float, str)):
        return _safe_float(price_info)
    if not isinstance(price_info, dict):
        return None
    for key in ("regular", "promo", "currentPrice", "price", "amount", "displayPrice"):
        value = price_info.get(key)
        if value is None:
            continue
        price = _safe_float(value)
        if price is not None:
            return price
    return None


def _today() -> str:
    return datetime.now(UTC).date().isoformat()
