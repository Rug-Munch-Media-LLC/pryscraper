"""Pry — travel hotels: hotel rate lookups (Google Hotels + Booking + Kayak + Expedia).

There is no free, keyless hotel-rate API, so this module scrapes four public
search pages in a guarded fallback chain:

* Google Hotels (primary) — ``https://www.google.com/travel/hotels`` with
  ``q``/``check_in``/``check_out`` params; rates are read from the embedded
  ``AF_initDataCallback`` JSON (same infrastructure as :mod:`travel.flights`).
* Booking.com (fallback 2) — ``https://www.booking.com/searchresults.html``
  with ``ss``/``checkin``/``checkout`` params; rates are read from embedded
  ``data-capla-trace`` JSON blocks, with a light regex fallback on the raw
  HTML when the JSON blocks are absent.
* Kayak (fallback 3) — ``https://www.kayak.com/hotels/{query}/{checkin}/
  {checkout}/2adults``; rates are read from the embedded
  ``window.__INITIAL_STATE__`` JSON via a string-aware balanced-brace scan.
* Expedia (fallback 4) — ``https://www.expedia.com/Hotel-Search`` with
  ``destination``/``checkInDate``/``checkOutDate`` params; rates are read
  from the page's ``application/ld+json`` structured-data blocks.

The chain is sequential: each source is only fetched when the previous one
yielded no rates, which keeps rate-limit pressure bounded.

Contract
--------
* async, never raise
* ``get_hotel_rates(hotel_name, checkin, checkout) -> dict`` with shape
  ``{"hotel", "rates": [{"site", "price_per_night", "currency", "total"}],
  "availability"}`` — ``availability`` is ``"available"`` when at least one
  rate was found, ``"unavailable"`` when a page was fetched but yielded no
  rates, ``"unknown"`` when nothing could be fetched. ``total`` may be
  absent (``None``) when the source only exposes a per-night price. Rates
  are aggregated per source site (cheapest per site).

Reliability (read before shipping)
----------------------------------
Google Hotels embeds its results as the same drifting, unversioned
``AF_initDataCallback`` JSON as Flights; Booking.com's ``data-capla-trace``
blocks are obfuscated and change regularly; Kayak's ``__INITIAL_STATE__``
and Expedia's JSON-LD are also layout-coupled and best-effort. Extraction is
signature-based and best-effort: layout changes degrade to ``{}``/empty
rates, never an exception. All four sources rate-limit / bot-guard page
hits — keep lookups bounded and respect the backoff knobs. Expedia in
particular frequently serves a bot/consent wall instead of results; treat
output as estimates.

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
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from travel.flights import _extract_af_callbacks, _walk_dicts

logger = logging.getLogger(__name__)

_GOOGLE_URL = "https://www.google.com/travel/hotels"
_BOOKING_URL = "https://www.booking.com/searchresults.html"
_KAYAK_URL = "https://www.kayak.com/hotels"
_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"

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


# ── Google Hotels extraction ───────────────────────────────────────────
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


def _find_google_rates(data: Any) -> list[dict[str, Any]]:
    """Locate hotel-rate-like records in Google Hotels embedded data."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(data):
        name = _extract_hotel_name(obj)
        if name is None:
            continue
        price = _extract_price_per_night(obj)
        if price is None:
            continue
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": name,
                "price_per_night": price,
                "currency": _extract_currency(obj),
                "total": _extract_total(obj),
            }
        )
    rates.sort(key=lambda entry: (entry["price_per_night"], entry["hotel"]))
    return rates


# ── Booking.com extraction ─────────────────────────────────────────────
def _extract_capla_blocks(html: str) -> list[str]:
    """Pull the ``data-capla-trace`` JSON script bodies out of a page."""
    blocks: list[str] = []
    for match in re.finditer(
        r'<script[^>]*type="application/json"[^>]*data-capla-trace[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        body = match.group(1).strip()
        if body:
            blocks.append(body)
    return blocks


def _find_booking_rates(html: str) -> list[dict[str, Any]]:
    """Locate hotel-rate records in a Booking.com searchresults page."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for block in _extract_capla_blocks(html):
        try:
            payload = json.loads(block)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        for obj in _walk_dicts(payload):
            name = _extract_hotel_name(obj)
            if name is None:
                continue
            price = _extract_price_per_night(obj)
            if price is None:
                continue
            key = (name, price)
            if key in seen:
                continue
            seen.add(key)
            rates.append(
                {
                    "hotel": name,
                    "price_per_night": price,
                    "currency": _extract_currency(obj),
                    "total": _extract_total(obj),
                }
            )

    # Regex fallback: data-price attributes / $1,234-style price markers.
    for match in _PRICE_RE.finditer(html):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        try:
            price = int(raw)
        except ValueError:
            continue
        if not (20 <= price <= 100_000):
            continue
        key = ("", price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": "",
                "price_per_night": price,
                "currency": _currency_for_match(html, match.start()),
                "total": None,
            }
        )
    return rates


def _currency_for_match(html: str, pos: int) -> str:
    """Best-effort currency for a regex price hit by inspecting nearby text."""
    window = html[max(0, pos - 60) : pos + 10]
    for symbol, currency in _CURRENCY_BY_SYMBOL.items():
        if symbol in window:
            return currency
    return "USD"


# ── Kayak extraction (embedded __INITIAL_STATE__ JSON) ────────────────
def _extract_embedded_object(html: str, marker: str) -> Any:
    """Extract the JS object/array assigned after ``marker`` (balanced scan).

    Kayak (and many React/Redux sites) embed their state as
    ``window.__INITIAL_STATE__ = {...};`` — a plain JS literal, not a
    JSON-typed script tag. The scanner walks braces with string awareness and
    decodes the captured literal. Returns ``None`` on any failure.
    """
    idx = html.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    while start < len(html) and html[start] not in "{[":  # allow arrays too
        start += 1
    if start >= len(html):
        return None
    opener = html[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(html):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    break
        i += 1
    if depth != 0:
        return None
    raw = html[start : i + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _find_kayak_rates(data: Any) -> list[dict[str, Any]]:
    """Locate hotel-rate-like records in Kayak's embedded state.

    Kayak hotel records look like ``{"name": ..., "price": {"price": <int>,
    "currency": "USD"}}``. Signature-based and best-effort, matching the
    module's layout-tolerant extraction philosophy.
    """
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(data):
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not (2 <= len(name) <= 80) or "\n" in name:
            continue
        price_obj = obj.get("price")
        if not isinstance(price_obj, dict):
            continue
        raw_price = price_obj.get("price")
        if not isinstance(raw_price, (int, float)) or not (20 <= raw_price <= 100_000):
            continue
        price = int(raw_price)
        currency = str(price_obj.get("currency") or "").strip().upper()
        if not _CURRENCY_RE.fullmatch(currency):
            currency = "USD"
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": name,
                "price_per_night": price,
                "currency": currency,
                "total": None,
            }
        )
    rates.sort(key=lambda entry: (entry["price_per_night"], entry["hotel"]))
    return rates


# ── Expedia extraction (JSON-LD structured data) ──────────────────────
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _extract_json_ld(html: str) -> list[Any]:
    """Parse every ``application/ld+json`` block on a page (never raises)."""
    blocks: list[Any] = []
    for match in _LD_JSON_RE.finditer(html):
        body = match.group(1).strip()
        if not body:
            continue
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            blocks.extend(parsed)
        elif isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def _ld_price(obj: dict[str, Any]) -> int | None:
    """Best-effort per-night price from a JSON-LD hotel/offer node."""
    offers = obj.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price")
        if isinstance(price, (int, float)) and 20 <= price <= 100_000:
            return int(price)
        spec = offers.get("priceSpecification")
        if isinstance(spec, dict):
            price = spec.get("price")
            if isinstance(price, (int, float)) and 20 <= price <= 100_000:
                return int(price)
    price = obj.get("price")
    if isinstance(price, (int, float)) and 20 <= price <= 100_000:
        return int(price)
    return None


def _find_expedia_rates(html: str) -> list[dict[str, Any]]:
    """Locate hotel-rate records in an Expedia page's JSON-LD blocks."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(_extract_json_ld(html)):
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not (2 <= len(name) <= 80) or "\n" in name:
            continue
        price = _ld_price(obj)
        if price is None:
            continue
        currency = str(obj.get("priceCurrency") or obj.get("currency") or "USD").upper()
        if not _CURRENCY_RE.fullmatch(currency):
            currency = "USD"
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": name,
                "price_per_night": price,
                "currency": currency,
                "total": None,
            }
        )
    rates.sort(key=lambda entry: (entry["price_per_night"], entry["hotel"]))
    return rates


def _kayak_search_url(name: str, checkin: str, checkout: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        slug = quote(name.strip())
    return f"{_KAYAK_URL}/{slug}/{checkin}/{checkout}/2adults"


# ── public API ─────────────────────────────────────────────────────────
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


async def get_hotel_rates(hotel_name: str, checkin: str, checkout: str) -> dict[str, Any]:
    """Look up per-night rates for ``hotel_name`` between two dates.

    Args:
        hotel_name: Free-text hotel name / location query.
        checkin: Check-in date as ``YYYY-MM-DD``.
        checkout: Check-out date as ``YYYY-MM-DD``.

    Returns:
        ``{"hotel", "rates": [{"site", "price_per_night", "currency",
        "total"}], "availability"}``. Rates are aggregated per source site
        (cheapest per site). The fallback chain is sequential — Google Hotels
        -> Booking.com -> Kayak -> Expedia — each source fetched only when
        the previous one yielded no rates. Never raises.
    """
    name = hotel_name.strip() if isinstance(hotel_name, str) else ""
    if not name or not _valid_date(checkin) or not _valid_date(checkout):
        return _empty_result(name, "unknown")

    fetched_any = False
    rates_by_site: dict[str, dict[str, Any]] = {}

    # 1. Primary: Google Hotels.
    google_html = await _fetch_page(
        _GOOGLE_URL,
        {
            "q": name,
            "check_in": checkin,
            "check_out": checkout,
            "hl": "en",
            "gl": "us",
        },
    )
    if google_html:
        fetched_any = True
        for callback in _extract_af_callbacks(google_html):
            for entry in _find_google_rates(callback.get("data")):
                _aggregate_site_rates(rates_by_site, "google", entry)

    # 2. Booking.com (only if Google yielded nothing).
    if "google" not in rates_by_site:
        booking_html = await _fetch_page(
            _BOOKING_URL,
            {
                "ss": name,
                "checkin": checkin,
                "checkout": checkout,
                "group_adults": "2",
                "no_rooms": "1",
                "lang": "en-us",
                "selected_currency": "USD",
            },
        )
        if booking_html:
            fetched_any = True
            for entry in _find_booking_rates(booking_html):
                _aggregate_site_rates(rates_by_site, "booking", entry)

    # 3. Kayak (embedded __INITIAL_STATE__ JSON).
    if not rates_by_site:
        kayak_html = await _fetch_page(_kayak_search_url(name, checkin, checkout), {})
        if kayak_html:
            fetched_any = True
            state = _extract_embedded_object(kayak_html, "window.__INITIAL_STATE__")
            for entry in _find_kayak_rates(state):
                _aggregate_site_rates(rates_by_site, "kayak", entry)

    # 4. Expedia (JSON-LD structured data).
    if not rates_by_site:
        expedia_html = await _fetch_page(
            _EXPEDIA_URL,
            {
                "destination": name,
                "checkInDate": checkin,
                "checkOutDate": checkout,
                "adults": "2",
                "rooms": "1",
            },
        )
        if expedia_html:
            fetched_any = True
            for entry in _find_expedia_rates(expedia_html):
                _aggregate_site_rates(rates_by_site, "expedia", entry)

    rates = sorted(rates_by_site.values(), key=lambda entry: entry["site"])
    if rates:
        return {"hotel": name, "rates": rates, "availability": "available"}
    if fetched_any:
        return _empty_result(name, "unavailable")
    return _empty_result(name, "unknown")
