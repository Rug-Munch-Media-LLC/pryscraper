"""Pry — travel hotels: shared helpers (fetching, validation, field extraction).

Common infrastructure for the per-platform hotel-rate modules
(:mod:`hotels_google`, :mod:`hotels_booking`, :mod:`hotels_kayak`,
:mod:`hotels_expedia`) and the :mod:`hotels` facade.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PRICE_RE = re.compile(
    r"(?:data-price=\"(\d+)\"|(?:[\$\u20ac\u00a3\u00a5]|CA\$|A\$)\s*(\d{2,6})(?:\.\d{2})?)"
)

_CURRENCY_BY_SYMBOL: dict[str, str] = {
    "$": "USD",
    "\u20ac": "EUR",
    "\u00a3": "GBP",
    "\u00a5": "JPY",
    "CA$": "CAD",
    "A$": "AUD",
}


def _valid_date(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not _DATE_RE.fullmatch(value):
        return False
    try:
        from datetime import datetime

        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


async def _fetch_page(url: str, params: dict[str, str]) -> str:
    """GET a travel page with capped exponential backoff (never raises)."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("hotels_fetch_failed", extra={"url": url[:80], "error": last_error})
    return ""


def _extract_hotel_name(obj: dict[str, Any]) -> str | None:
    """Best-effort hotel name from a candidate record."""
    for key, value in obj.items():
        if (
            isinstance(value, str)
            and isinstance(key, str)
            and re.search(r"name|hotel|title", key, re.IGNORECASE)
        ):
            candidate = value.strip()
            if 2 <= len(candidate) <= 80 and "\n" not in candidate:
                return candidate
    for value in obj.values():
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if not (2 <= len(candidate) <= 80 and "\n" not in candidate):
            continue
        if _DATE_RE.fullmatch(candidate) or _CURRENCY_RE.fullmatch(candidate):
            continue
        return candidate
    return None


def _extract_price_per_night(obj: dict[str, Any]) -> int | None:
    """Best-effort per-night price (int) from a candidate record."""
    fallback: int | None = None
    for key, value in obj.items():
        if not isinstance(value, int) or not (20 <= value <= 100_000):
            continue
        if isinstance(key, str) and re.search(r"price|night|amount|rate", key, re.IGNORECASE):
            return value
        if fallback is None:
            fallback = value
    return fallback


def _extract_total(obj: dict[str, Any]) -> int | None:
    """Best-effort total stay price (int) from a candidate record."""
    for key, value in obj.items():
        if (
            isinstance(value, int)
            and (20 <= value <= 500_000)
            and isinstance(key, str)
            and re.search(r"total|sum", key, re.IGNORECASE)
        ):
            return value
    return None


def _extract_currency(obj: dict[str, Any]) -> str:
    """Best-effort currency code (default ``USD``) from a candidate record."""
    for key, value in obj.items():
        if (
            isinstance(value, str)
            and isinstance(key, str)
            and re.search(r"currency", key, re.IGNORECASE)
        ):
            candidate = value.strip().upper()
            if _CURRENCY_RE.fullmatch(candidate):
                return candidate
    return "USD"


def _currency_for_match(html: str, pos: int) -> str:
    """Best-effort currency for a regex price hit by inspecting nearby text."""
    window = html[max(0, pos - 60) : pos + 10]
    for symbol, currency in _CURRENCY_BY_SYMBOL.items():
        if symbol in window:
            return currency
    return "USD"


def _empty_result(hotel_name: str, availability: str) -> dict[str, Any]:
    return {
        "hotel": hotel_name,
        "rates": [],
        "availability": availability,
    }


def _aggregate_site_rates(
    rates_by_site: dict[str, dict[str, Any]], site: str, entry: dict[str, Any]
) -> None:
    """Keep the cheapest rate per source site in ``rates_by_site``."""
    site_rate = rates_by_site.setdefault(
        site,
        {
            "site": site,
            "price_per_night": entry["price_per_night"],
            "currency": entry["currency"],
            "total": entry["total"],
        },
    )
    if entry["price_per_night"] < site_rate["price_per_night"]:
        site_rate["price_per_night"] = entry["price_per_night"]
        site_rate["currency"] = entry["currency"]
        site_rate["total"] = entry["total"]
