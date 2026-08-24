"""Pry — travel flights: Google Flights scraping (no public API).

Google Flights has no public search API, so this module drives the public
search deep-link page directly:

1. Encode the search (origin, destination, date) into the ``tfs`` query
   parameter — a Base64-encoded protobuf payload. The wire format is
   reverse-engineered from the current ``fast-flights`` encoder and
   verified byte-for-byte against a known-good round-trip example
   (``CBwQAh...AZgBAQ`` for TPE→MYJ 2024-05-28).
2. GET ``https://www.google.com/travel/flights/flights`` with that ``tfs``.
3. Extract the ``AF_initDataCallback({...})`` JSON payloads embedded in the
   page and locate flight-option-like records with a defensive signature
   search (price + airline + duration), because the exact array layout
   drifts frequently.

Contract
--------
* async, never raise
* ``search_flights(origin, dest, date, limit=20) -> list[dict]`` where each
  entry is ``{"date", "price", "airline", "duration", "stops"}`` — price in
  USD (int), duration in minutes (int), stops int (0 = nonstop). Sorted by
  price ascending.
* ``cheapest_date_grid(origin, dest, start_date, end_date) -> list[dict]`` —
  the cheapest option per day, same entry shape, sorted by date ascending.
  Days whose page could not be fetched/parsed are omitted.

Reliability (read before shipping)
----------------------------------
The embedded ``AF_initDataCallback`` JSON on Google Flights is an
unversioned, frequently-changing internal format. Extraction here is
signature-based and best-effort: when the layout shifts, results silently
degrade to ``[]`` (never an exception). Google also rate-limits aggressive
page hits — keep grids bounded (``_MAX_GRID_DAYS``, default 30) and respect
the backoff knobs. Treat every result as a best-effort estimate.

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
import base64
import json
import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.google.com/travel/flights/flights"
_CURRENCY = "USD"

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

# Grid bounds: never fetch more than this many days in one call, and cap
# per-day option scans so a single grid run stays within sane HTTP volume.
_MAX_GRID_DAYS = 30
_GRID_CONCURRENCY = 4
_MAX_RESULTS = 200

_AIRLINE_RE = re.compile(r"^[A-Za-z][A-Za-z .&'\-]{1,39}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE_RE = re.compile(r"^[A-Z]{3}$")
_DURATION_STR_RE = re.compile(
    r"(?:(\d+)\s*(?:hr|h|hour)s?)?\s*(?:(\d+)\s*(?:min|m))?", re.IGNORECASE
)


# ── tfs protobuf encoder (wire format, hand-rolled — no protobuf dep) ──
def _varint(value: int) -> bytes:
    """Encode an unsigned LEB128 varint (protobuf wire format)."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(num: int, payload: bytes) -> bytes:
    """Encode a length-delimited protobuf field (tag + length + payload)."""
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _encode_airport(code: str) -> bytes:
    """Encode an ``Airport { f1: 1, f2: <IATA> }`` message."""
    return b"\x08\x01" + _field(2, code.encode())


def _encode_leg(date: str, origin: str, dest: str) -> bytes:
    """Encode one ``FlightInfo`` leg (f3 of the top-level message)."""
    payload = _field(2, date.encode())
    payload += _field(13, _encode_airport(origin))
    payload += _field(14, _encode_airport(dest))
    return _field(3, payload)


def _build_tfs(legs: Iterable[tuple[str, str, str]]) -> str:
    """Build the Base64url ``tfs`` search parameter for the given legs.

    Each leg is a ``(date, origin, dest)`` tuple with ``date`` as
    ``YYYY-MM-DD`` and 3-letter IATA codes. The fixed header/tail bytes are
    the values emitted by the current ``fast-flights`` encoder for a
    one-way economy search with 1 adult (verified byte-for-byte).
    """
    full = b"\x08\x1c\x10\x02"
    for date, origin, dest in legs:
        full += _encode_leg(date, origin, dest)
    full += b"\x40\x01\x48\x01\x70\x01"
    full += b"\x82\x01\x0b\x08\xff\xff\xff\xff\xf0\x19\x80\x10\x10"
    return base64.urlsafe_b64encode(full).decode("ascii").rstrip("=")


# ── date / airport-code validation ─────────────────────────────────────
def _valid_date(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not _DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_code(value: str) -> str:
    if not isinstance(value, str):
        return ""
    code = value.strip().upper()
    return code if _CODE_RE.fullmatch(code) else ""


def _date_range(start_date: str, end_date: str) -> list[str]:
    """List ``YYYY-MM-DD`` strings in ``[start_date, end_date]`` (bounded)."""
    if not _valid_date(start_date) or not _valid_date(end_date):
        return []
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return []
    if end < start:
        return []
    end = min(end, start + timedelta(days=_MAX_GRID_DAYS - 1))
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


async def _fetch_page(tfs: str) -> str:
    """Fetch the Google Flights deep-link page HTML (never raises)."""
    params = {"hl": "en", "curr": _CURRENCY, "tfs": tfs}
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(_SEARCH_URL, params=params)
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
    logger.warning("flights_fetch_failed", extra={"error": last_error})
    return ""


# ── embedded JSON extraction ───────────────────────────────────────────
def _match_paren(text: str, open_idx: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``open_idx`` (or -1)."""
    depth = 0
    in_string = False
    quote = ""
    i = open_idx
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                in_string = False
        elif ch in "'\"":
            in_string = True
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _quotes_to_json(text: str) -> str:
    """Convert Google's single-quoted JS object literal to strict JSON.

    Google's ``AF_initDataCallback`` payloads use single quotes for keys and
    string values and bare identifiers for object keys (``key: 'ds:1'``).
    This normalizes quote style (single -> double, outside existing double
    strings) and then quotes bare identifiers used as object keys.
    Flight/hotel payloads are made of airport codes, dates, prices and
    airline names — apostrophes inside strings are not expected, so the
    wholesale normalization is safe here. Callers must treat this as
    best-effort; a failed parse simply skips that callback.
    """
    # Pass 1: normalize single-quoted strings to double-quoted (outside
    # existing double-quoted strings, which are copied verbatim).
    normalized: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            normalized.append('"')
            i += 1
            while i < n:
                c = text[i]
                if c == "\\":
                    normalized.append(c)
                    if i + 1 < n:
                        normalized.append(text[i + 1])
                        i += 2
                    continue
                if c == "'":
                    normalized.append('"')
                    i += 1
                    break
                normalized.append(c)
                i += 1
            continue
        if ch == '"':
            normalized.append(ch)
            i += 1
            while i < n:
                c = text[i]
                normalized.append(c)
                if c == "\\" and i + 1 < n:
                    normalized.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                i += 1
            continue
        normalized.append(ch)
        i += 1

    # Pass 2: quote bare identifiers followed by ':' (object keys).
    body = "".join(normalized)
    out: list[str] = []
    i = 0
    n = len(body)
    in_string = False
    while i < n:
        ch = body[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(body[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (body[j].isalnum() or body[j] in "_$"):
                j += 1
            k = j
            while k < n and body[k].isspace():
                k += 1
            if k < n and body[k] == ":":
                out.append('"')
                out.append(body[i:j])
                out.append('"')
                i = j
                continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_af_callbacks(html: str) -> list[dict[str, Any]]:
    """Extract every ``AF_initDataCallback({...})`` payload from a page.

    Returns a list of ``{"key": ..., "hash": ..., "data": ..., ...}`` dicts.
    Malformed callbacks are skipped — this never raises.
    """
    results: list[dict[str, Any]] = []
    start = 0
    marker = "AF_initDataCallback("
    while True:
        idx = html.find(marker, start)
        if idx == -1:
            break
        open_idx = idx + len(marker) - 1
        end = _match_paren(html, open_idx)
        if end == -1:
            # Malformed callback — keep scanning for later ones.
            start = open_idx + 1
            continue
        body = html[open_idx + 1 : end]
        try:
            obj = json.loads(_quotes_to_json(body))
        except (json.JSONDecodeError, ValueError, TypeError):
            start = end + 1
            continue
        if isinstance(obj, dict):
            results.append(obj)
        start = end + 1
    return results


# ── flight-option detection (signature-based, layout-tolerant) ─────────
def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Depth-first walk yielding every dict nested in ``value``."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _extract_price(obj: dict[str, Any]) -> int | None:
    """Best-effort price (USD int) from a candidate record."""
    fallback: int | None = None
    for key, value in obj.items():
        if not isinstance(value, int) or not (10 <= value <= 100_000):
            continue
        if isinstance(key, str):
            if re.search(r"price|cost|total|amount", key, re.IGNORECASE):
                return value
            # Duration/timestamp ints (e.g. a 380-minute flight) must not
            # masquerade as a price in the fallback path.
            if re.search(r"dur|time|stop|hour|minute|epoch", key, re.IGNORECASE):
                continue
        if fallback is None:
            fallback = value
    return fallback


def _extract_airline(obj: dict[str, Any]) -> str | None:
    """Best-effort airline name/code from a candidate record."""
    for key, value in obj.items():
        if (
            isinstance(value, str)
            and isinstance(key, str)
            and re.search(r"airline|carrier|operator", key, re.IGNORECASE)
        ):
            candidate = value.strip()
            if _AIRLINE_RE.fullmatch(candidate):
                return candidate
    for value in obj.values():
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if not _AIRLINE_RE.fullmatch(candidate):
            continue
        if _DATE_RE.fullmatch(candidate):
            continue
        if len(candidate) <= 4 and candidate.isupper():
            continue  # airport code, not an airline
        return candidate
    return None


def _extract_duration(obj: dict[str, Any]) -> int | None:
    """Best-effort flight duration in minutes from a candidate record."""
    # Prefer keys that explicitly reference duration / time.
    for key, value in obj.items():
        if (
            isinstance(value, int)
            and 30 <= value <= 86_400
            and isinstance(key, str)
            and re.search(r"dur|time|total|flight", key, re.IGNORECASE)
        ):
            return value
    # Fallback: any plausible minute count — but never a price/amount int.
    for key, value in obj.items():
        if isinstance(value, int) and 30 <= value <= 86_400:
            if isinstance(key, str) and re.search(
                r"price|cost|amount|currency|stops?", key, re.IGNORECASE
            ):
                continue
            return value
    for value in obj.values():
        if isinstance(value, str):
            match = _DURATION_STR_RE.search(value)
            if match and (match.group(1) or match.group(2)):
                hours = int(match.group(1) or 0)
                minutes = int(match.group(2) or 0)
                if hours or minutes:
                    return hours * 60 + minutes
    return None


def _extract_stops(obj: dict[str, Any]) -> int:
    """Best-effort stop count from a candidate record (default 0)."""
    for key, value in obj.items():
        if (
            isinstance(value, int)
            and 0 <= value <= 5
            and isinstance(key, str)
            and re.search(r"stop", key, re.IGNORECASE)
        ):
            return value
    for value in obj.values():
        if isinstance(value, str):
            if re.fullmatch(r"Non-?stop", value, re.IGNORECASE):
                return 0
            match = re.fullmatch(r"(\d+)\s*stops?", value, re.IGNORECASE)
            if match:
                return int(match.group(1))
    return 0


def _child_dicts(obj: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield the direct dict children of ``obj`` (values and list items)."""
    for value in obj.values():
        if isinstance(value, dict):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item


def _find_flight_options(data: Any) -> list[dict[str, Any]]:
    """Locate flight-option-like records in embedded data (never raises).

    Scans every nested dict for a price + airline + duration signature and
    returns normalized, de-duplicated records sorted by price ascending.
    Real Google payloads often split the signature across a parent dict
    (price) and a direct child dict (airline / duration), so those are
    merged before acceptance.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int]] = set()

    def _emit(price: int, airline: str, duration: int, stops: int) -> None:
        key = (price, airline, duration, stops)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {"price": price, "airline": airline, "duration": duration, "stops": stops}
        )

    for obj in _walk_dicts(data):
        price = _extract_price(obj)
        if price is None:
            continue
        airline = _extract_airline(obj)
        duration = _extract_duration(obj)
        if airline is None or duration is None:
            for child in _child_dicts(obj):
                if airline is None:
                    airline = _extract_airline(child)
                if duration is None:
                    duration = _extract_duration(child)
                if airline is not None and duration is not None:
                    break
        if airline is None or duration is None:
            continue
        _emit(price, airline, duration, _extract_stops(obj))
    candidates.sort(key=lambda entry: (entry["price"], entry["airline"]))
    return candidates


# ── public API ─────────────────────────────────────────────────────────
async def search_flights(
    origin: str, dest: str, date: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Google Flights for one-way options on ``date``.

    Args:
        origin: 3-letter IATA origin airport code (e.g. ``JFK``).
        dest: 3-letter IATA destination airport code (e.g. ``CDG``).
        date: Departure date as ``YYYY-MM-DD``.
        limit: Max results (clamped to 1..200).

    Returns:
        List of ``{"date", "price", "airline", "duration", "stops"}`` dicts
        sorted by price ascending. Empty list on any failure.
    """
    origin_code = _normalize_code(origin)
    dest_code = _normalize_code(dest)
    if not origin_code or not dest_code or not _valid_date(date):
        return []
    try:
        tfs = _build_tfs([(date, origin_code, dest_code)])
    except (TypeError, ValueError, UnicodeEncodeError):
        return []
    html = await _fetch_page(tfs)
    if not html:
        return []
    options: list[dict[str, Any]] = []
    for callback in _extract_af_callbacks(html):
        options.extend(_find_flight_options(callback.get("data")))
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int]] = set()
    for option in options:
        key = (option["price"], option["airline"], option["duration"], option["stops"])
        if key in seen:
            continue
        seen.add(key)
        results.append({"date": date, **option})
    return results[: max(1, min(limit, _MAX_RESULTS))]


async def cheapest_date_grid(
    origin: str, dest: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Cheapest flight per day between ``start_date`` and ``end_date``.

    Args:
        origin: 3-letter IATA origin airport code.
        dest: 3-letter IATA destination airport code.
        start_date: First date as ``YYYY-MM-DD``.
        end_date: Last date as ``YYYY-MM-DD`` (bounded to 30 days).

    Returns:
        One ``{"date", "price", "airline", "duration", "stops"}`` per day
        (the cheapest option), sorted by date ascending. Days whose page
        could not be fetched/parsed are omitted.
    """
    origin_code = _normalize_code(origin)
    dest_code = _normalize_code(dest)
    dates = _date_range(start_date, end_date)
    if not origin_code or not dest_code or not dates:
        return []

    semaphore = asyncio.Semaphore(_GRID_CONCURRENCY)

    async def _cheapest_for(day: str) -> dict[str, Any] | None:
        async with semaphore:
            flights = await search_flights(origin_code, dest_code, day, limit=5)
        if not flights:
            return None
        # Defensive: the source is expected to sort by price, but pick the
        # true minimum explicitly so ordering drift cannot leak through.
        return min(flights, key=lambda entry: entry["price"])

    rows = await asyncio.gather(*(_cheapest_for(day) for day in dates))
    cheapest = [row for row in rows if row is not None]
    cheapest.sort(key=lambda row: row["date"])
    return cheapest
