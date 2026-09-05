"""Embedded-JSON extraction and flight-option detection for Google Flights.

Google Flights embeds ``AF_initDataCallback({...})`` JSON payloads in the
page. Extraction here is signature-based and best-effort: when the layout
shifts, results silently degrade to ``[]`` (never an exception).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from datasets.travel.flights_common import (
    _AIRLINE_RE,
    _DATE_RE,
    _DURATION_STR_RE,
)


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
