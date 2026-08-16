"""Google Maps local-business data extraction for Pry.

Scrapes the public Google Maps search page (``google.com/maps/search/...``)
for local-business listings and the place page (``?cid=`` / ``/place/``)
for detail + popular times. This is lead-gen data: name, address, phone,
rating, review count, category, website and opening hours.

Data sources, in priority order:

1. ``application/ld+json`` script blocks embedded in the page — stable,
   documented fields (name, address, rating, review count, hours).
2. The ``window._p`` / ``window.APP_INITIALIZATION_STATE`` JS blobs — the
   full listing payload (phone, category, website, popular times). These
   blobs are undocumented; Google moves the indexes without notice, so the
   blob parser below is deliberately shape-based and defensive — every
   field defaults to ``""`` / ``None`` rather than raising.

Anti-bot note:
    Google Maps is a JavaScript-heavy page. A plain HTTP GET returns the
    HTML shell with the embedded JSON, but Google frequently gates it
    behind consent walls / "unusual traffic" / captcha challenges. When
    that happens the module logs ``google_maps_anti_bot`` and returns
    empty results — the escalation path is the repo's browser/stealth
    tier (``camoufox_integration``, ``stealth_engine``), not this module.

Contract:
    * ``search_places(query, location, limit)`` → list of normalized records
    * ``get_place(place_id)`` → single record + ``popular_times``

Both are async and never raise; on any failure they return ``[]`` / ``{}``.
robots.txt is respected (best-effort, fail-open — see ``_robots_allowed``).
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
import os
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

if TYPE_CHECKING:
    from collections.abc import Iterator

import httpx

from client import get_client

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_RETRIES = 3
RETRY_BASE = 0.8
MAX_BACKOFF = 6.0
RESULT_CACHE_TTL = 30.0  # in-memory result cache TTL (seconds)
ROBOTS_CACHE_TTL = 300.0  # robots.txt per-host cache TTL (seconds)

GOOGLE_MAPS_SEARCH = "https://www.google.com/maps/search/{query}"
GOOGLE_MAPS_CID = "https://www.google.com/maps?cid={cid}"
GOOGLE_MAPS_PLACE = "https://www.google.com/maps/place/{slug}"

# Browser-ish headers: Google serves the JS page (with the embedded JSON
# blobs) to normal user agents; a bare "pry/3.0" UA gets the no-JS shell.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_BUSINESS_TYPES = frozenset(
    {
        "LocalBusiness",
        "Restaurant",
        "CafeOrCoffeeShop",
        "TouristAttraction",
        "Place",
        "Store",
        "BarOrPub",
        "FoodEstablishment",
        "LodgingBusiness",
        "BeautySalon",
        "HealthClub",
        "AutomotiveBusiness",
        "ShoppingCenter",
        "NightClub",
        "Bakery",
        "Dentist",
        "Doctor",
        "Hospital",
        "School",
        "Library",
        "Museum",
        "Park",
        "MovieTheater",
        "BowlingAlley",
    }
)

_DAY_NAMES = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]

_SHORT_DAY = {
    "Monday": "Mon",
    "Tuesday": "Tue",
    "Wednesday": "Wed",
    "Thursday": "Thu",
    "Friday": "Fri",
    "Saturday": "Sat",
    "Sunday": "Sun",
}

_ANTI_BOT_SIGNALS = (
    "unusual traffic",
    "are you a robot",
    "enable javascript",
    "not a robot",
    "recaptcha",
    "captcha",
    "consent.google.com",
)

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_BLOB_ASSIGN_RE = re.compile(r"window\.(_p|APP_INITIALIZATION_STATE)\s*=")

_cache: dict[str, tuple[float, Any]] = {}
_robots_cache: dict[str, tuple[float, bool]] = {}


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    _cache.clear()
    _robots_cache.clear()


# ── Small coercion helpers ───────────────────────────────────────────────
def _opt_float(value: Any) -> float | None:
    """Coerce a value to float; None on any failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    """Coerce a value to int, tolerating "2,341 reviews" style strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _safe_str(value: Any) -> str:
    """Return value when it is a str, else ""."""
    return value if isinstance(value, str) else ""


def _cache_get(key: str) -> Any | None:
    """Return a cached value, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > RESULT_CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    """Store a value under ``key``."""
    _cache[key] = (time.monotonic(), value)


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    """Exponential backoff, honoring Retry-After when present."""
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF)
            except ValueError:
                pass
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


# ── HTTP with timeout + backoff ──────────────────────────────────────────
async def _http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> httpx.Response | None:
    """GET with browser headers, timeouts, and exponential backoff.

    Retries on 429 (honoring Retry-After) and 5xx. Never raises: returns
    None on transport errors or after exhausting retries.
    """
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    client = await get_client()
    attempt = 0
    while True:
        try:
            resp = await client.get(
                url,
                params=params,
                headers=merged,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.warning("http_error", extra={"url": url, "error": str(exc)[:200]})
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= retries:
                logger.warning(
                    "http_retries_exhausted", extra={"url": url, "status": resp.status_code}
                )
                return None
            delay = _retry_delay(resp, attempt)
            logger.info(
                "http_backoff", extra={"url": url, "status": resp.status_code, "delay": delay}
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        return resp


# ── robots.txt (best-effort, fail-open) ──────────────────────────────────
async def _robots_allowed(url: str) -> bool:
    """Check robots.txt for ``url`` with a short per-host cache.

    Fails open (returns True) when robots.txt cannot be fetched or when
    ``PRY_LOCAL_RESPECT_ROBOTS`` is set to anything other than
    "1"/"true"/"yes"/"on". Reuses :func:`compliance.policy.check_robots_txt`.
    """
    if os.environ.get("PRY_LOCAL_RESPECT_ROBOTS", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    parsed = urlparse(url)
    key = f"{parsed.scheme}://{parsed.netloc}"
    now = time.monotonic()
    cached = _robots_cache.get(key)
    if cached and now - cached[0] < ROBOTS_CACHE_TTL:
        return cached[1]
    allowed = True
    try:
        from compliance.policy import check_robots_txt  # lazy: heavy import

        result = await check_robots_txt(url)
        allowed = bool(result.get("crawl_allowed", True))
        if not allowed:
            logger.warning(
                "robots_blocked",
                extra={"url": url, "matched": result.get("matched_disallow")},
            )
    except Exception:  # noqa: BLE001 — fail open; never break on robots errors
        allowed = True
    _robots_cache[key] = (now, allowed)
    return allowed


# ── Google Maps embedded JSON blobs ──────────────────────────────────────
def _extract_js_value(html: str, start: int) -> str | None:
    """Return the JS literal (string or array) beginning at ``start``.

    ``start`` is the position just after ``window.<name> =``. Scans either
    to the closing unescaped quote (string literal) or to the matching
    close bracket (array literal, respecting nested strings).
    """
    i = start
    n = len(html)
    while i < n and html[i] in " \t\r\n":
        i += 1
    if i >= n:
        return None
    first = html[i]
    if first == '"':
        j = i + 1
        while j < n:
            c = html[j]
            if c == "\\":
                j += 2
                continue
            if c == '"':
                return html[i : j + 1]
            j += 1
        return None
    if first == "[":
        depth = 0
        j = i
        in_str = False
        while j < n:
            c = html[j]
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        return html[i : j + 1]
            j += 1
        return None
    return None


def _js_unescape(raw: str) -> str:
    """Decode a JS string literal (\\xNN / \\uNNNN escapes) to text."""
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    out: list[str] = []
    i = 0
    n = len(raw)
    simple = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        '"': '"',
        "'": "'",
        "\\": "\\",
        "/": "/",
    }
    while i < n:
        c = raw[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "x" and i + 3 < n:
            try:
                out.append(chr(int(raw[i + 2 : i + 4], 16)))
            except ValueError:
                out.append("x")
            i += 4
            continue
        if nxt == "u" and i + 5 < n:
            try:
                out.append(chr(int(raw[i + 2 : i + 6], 16)))
            except ValueError:
                out.append("u")
            i += 6
            continue
        out.append(simple.get(nxt, nxt))
        i += 2
    return "".join(out)


def _js_escapes_to_json(text: str) -> str:
    """Convert JS escapes inside string literals of a JSON-ish array to JSON.

    Google's ``APP_INITIALIZATION_STATE`` arrays use JS ``\\xNN`` escapes
    that are not valid JSON; this rewrites string tokens to JSON escapes.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != '"':
            out.append(c)
            i += 1
            continue
        j = i + 1
        seg = ['"']
        while j < n:
            ch = text[j]
            if ch == "\\" and j + 1 < n:
                nxt = text[j + 1]
                if nxt == "x" and j + 3 < n:
                    seg.append("\\u00" + text[j + 2 : j + 4])
                    j += 4
                    continue
                if nxt == "u" and j + 5 < n:
                    seg.append("\\u" + text[j + 2 : j + 6])
                    j += 6
                    continue
                seg.append("\\" + nxt)
                j += 2
                continue
            if ch == '"':
                seg.append('"')
                j += 1
                break
            seg.append(ch)
            j += 1
        out.append("".join(seg))
        i = j
    return "".join(out)


def _decode_js_value(raw: str) -> Any:
    """Decode a JS literal (string or array) to a Python object."""
    if raw.startswith('"'):
        decoded = _js_unescape(raw)
        try:
            return json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            return decoded
    converted = _js_escapes_to_json(raw)
    try:
        return json.loads(converted)
    except (json.JSONDecodeError, ValueError):
        return None


def _jsonify(value: Any) -> Any:
    """Re-parse nested JSON strings (double-encoded ``_p`` blobs)."""
    seen = 0
    while isinstance(value, str) and seen < 3:
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            break
        seen += 1
    return value


def _extract_blobs(html: str) -> list[Any]:
    """Decode embedded Google Maps JSON blobs into Python objects.

    Supports ``window._p`` (a JS string literal that is itself JSON, often
    double-encoded and full of ``\\xNN`` escapes) and
    ``window.APP_INITIALIZATION_STATE`` (a raw JS array). Returns an empty
    list when nothing decodes — callers must treat that as "no data", not
    an error.
    """
    decoded: list[Any] = []
    for m in _BLOB_ASSIGN_RE.finditer(html):
        raw = _extract_js_value(html, m.end())
        if not raw:
            continue
        value = _decode_js_value(raw)
        if value is None:
            continue
        decoded.append(_jsonify(value))
    return decoded


def _iter_values(obj: Any, depth: int = 0) -> Iterator[Any]:
    """Yield every nested list/dict value up to ``depth``."""
    if depth > 8:
        return
    if isinstance(obj, list):
        yield obj
        for item in obj:
            yield from _iter_values(item, depth + 1)
    elif isinstance(obj, dict):
        yield obj
        for item in obj.values():
            yield from _iter_values(item, depth + 1)


def _is_anti_bot(html: str) -> bool:
    """Detect consent/captcha/"unusual traffic" walls in the first 300 KB."""
    low = html[:300_000].lower()
    return any(sig in low for sig in _ANTI_BOT_SIGNALS)


# ── JSON-LD parsing ──────────────────────────────────────────────────────
def _iter_dicts(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield nested dict values up to ``depth``."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        yield obj
        for item in obj.values():
            yield from _iter_dicts(item, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item, depth + 1)


def _looks_like_business(obj: dict[str, Any]) -> bool:
    """True for JSON-LD nodes that look like a local-business listing."""
    types = obj.get("@type") or obj.get("type") or []
    if isinstance(types, str):
        types = [types]
    if any(isinstance(t, str) and t in _BUSINESS_TYPES for t in types):
        return True
    return bool(obj.get("name") and (obj.get("address") or obj.get("aggregateRating")))


def _jsonld_items(html: str) -> list[dict[str, Any]]:
    """Parse application/ld+json blocks, returning business-like nodes."""
    items: list[dict[str, Any]] = []
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _iter_dicts(data):
            if _looks_like_business(obj):
                items.append(obj)
    return items


def _ld_address(value: Any) -> str:
    """Render a JSON-LD address (PostalAddress dict or plain string)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [
            value.get("streetAddress"),
            value.get("addressLocality"),
            value.get("addressRegion"),
            value.get("postalCode"),
            value.get("addressCountry"),
        ]
        return ", ".join(str(p) for p in parts if p)
    return ""


def _ld_hours(value: Any) -> str:
    """Render JSON-LD opening hours to "Mon, Fri: 08:00-15:00" style."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for spec in value:
            if isinstance(spec, str):
                parts.append(spec)
                continue
            if not isinstance(spec, dict):
                continue
            days = spec.get("dayOfWeek")
            if isinstance(days, str):
                days = [days]
            opens, closes = spec.get("opens"), spec.get("closes")
            if days and opens and closes:
                day_str = ", ".join(_SHORT_DAY.get(str(d), str(d)) for d in days)
                parts.append(f"{day_str}: {opens}-{closes}")
            elif opens and closes:
                parts.append(f"{opens}-{closes}")
        return "; ".join(parts)
    return ""


def _extract_cid(value: Any) -> str | None:
    """Extract a Google Maps CID from a URL / hex ftid string."""
    if not isinstance(value, str):
        return None
    m = re.search(r"[?&]cid=(\d+)", value)
    if m:
        return m.group(1)
    m = re.search(r"0x[0-9a-f]+:0x([0-9a-f]+)", value, re.IGNORECASE)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            return None
    return None


def _record_from_jsonld(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON-LD business node into the canonical record dict."""
    rating, review_count = None, None
    agg = item.get("aggregateRating")
    if isinstance(agg, dict):
        rating = _opt_float(agg.get("ratingValue"))
        review_count = _opt_int(agg.get("reviewCount"))
    types = item.get("@type") or item.get("type") or []
    if isinstance(types, str):
        types = [types]
    category = ", ".join(
        str(t) for t in types if isinstance(t, str) and t not in ("LocalBusiness", "Place")
    )
    url = item.get("url") or item.get("sameAs") or ""
    same_as = item.get("sameAs")
    website = ""
    if isinstance(same_as, str) and same_as.startswith("http") and "google" not in same_as.lower():
        website = same_as
    if (
        not website
        and isinstance(url, str)
        and url.startswith("http")
        and "google" not in url.lower()
    ):
        website = url
    return {
        "place_id": _extract_cid(url) or "",
        "name": str(item.get("name") or ""),
        "address": _ld_address(item.get("address")),
        "phone": str(item.get("telephone") or item.get("phone") or ""),
        "rating": rating,
        "review_count": review_count,
        "category": category,
        "website": website,
        "hours": _ld_hours(item.get("openingHoursSpecification") or item.get("openingHours")),
    }


# ── _p / APP_INITIALIZATION_STATE blob parsing ───────────────────────────
def _record_name(obj: list[Any]) -> str:
    """Extract the business name from a blob result tuple."""
    cell = obj[0]
    if isinstance(cell, list) and cell and isinstance(cell[0], str):
        return cell[0].strip()
    if isinstance(cell, str):
        return cell.strip()
    return ""


def _first_external_url(obj: Any, depth: int = 0) -> str:
    """First non-Google http(s) URL found in a nested structure."""
    if depth > 3:
        return ""
    if isinstance(obj, str):
        if obj.startswith(("http://", "https://")) and not re.search(
            r"google\.|gstatic|googleusercontent|schema\.org", obj
        ):
            return obj
        return ""
    if isinstance(obj, list):
        for item in obj:
            found = _first_external_url(item, depth + 1)
            if found:
                return found
    elif isinstance(obj, dict):
        for value in obj.values():
            found = _first_external_url(value, depth + 1)
            if found:
                return found
    return ""


def _record_from_blob_tuple(obj: list[Any]) -> dict[str, Any]:
    """Normalize a Google Maps blob result tuple into a record dict.

    Layout (current Maps embed; indexes drift, all optional):
        [0]  = [name, ...]  (name cell — may also be a plain string)
        [1]  = address
        [4]  = phone
        [9]  = [rating, review_count]
        [13] = category
    Website is discovered by scanning the tuple for a non-Google URL.
    """
    rating, review_count = None, None
    if len(obj) > 9 and isinstance(obj[9], (list, tuple)) and obj[9]:
        rating = _opt_float(obj[9][0])
        review_count = _opt_int(obj[9][1] if len(obj[9]) > 1 else None)
    website = _first_external_url(obj)
    return {
        "place_id": _extract_cid(website) or "",
        "name": _record_name(obj),
        "address": _safe_str(obj[1]) if len(obj) > 1 else "",
        "phone": _safe_str(obj[4]) if len(obj) > 4 else "",
        "rating": rating,
        "review_count": review_count,
        "category": _safe_str(obj[13]) if len(obj) > 13 else "",
        "website": website,
        "hours": "",
    }


def _blob_records(blobs: list[Any]) -> list[dict[str, Any]]:
    """Extract search-result records from decoded blobs (shape-based)."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blob in blobs:
        for obj in _iter_values(blob):
            if not isinstance(obj, list) or len(obj) < 10:
                continue
            name = _record_name(obj)
            if not name or not re.search(r"[A-Za-z]", name):
                continue
            key = name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            rec = _record_from_blob_tuple(obj)
            if rec.get("name"):
                records.append(rec)
    return records


def _parse_search_results(html: str) -> list[dict[str, Any]]:
    """Parse the Maps search page into normalized records (JSON-LD + blob).

    JSON-LD records win for the fields they carry; blob records fill the
    gaps (phone, website, category, ...). Records are deduplicated by
    normalized name, preserving first-seen order.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in _jsonld_items(html):
        rec = _record_from_jsonld(item)
        key = (rec.get("name") or "").strip().lower()
        if not key:
            continue
        if key not in merged:
            merged[key] = rec
            order.append(key)
        else:
            merged[key].update({k: v for k, v in rec.items() if v not in ("", None)})
    for rec in _blob_records(_extract_blobs(html)):
        key = (rec.get("name") or "").strip().lower()
        if not key:
            continue
        if key not in merged:
            merged[key] = rec
            order.append(key)
            continue
        existing = merged[key]
        for field, value in rec.items():
            if value not in ("", None) and existing.get(field) in ("", None):
                existing[field] = value
    return [merged[key] for key in order]


# ── Popular times ────────────────────────────────────────────────────────
def _looks_like_popular_times(obj: Any) -> bool:
    """True when ``obj`` is the classic [[day, [24 hour ints]] x7] shape."""
    if not isinstance(obj, list) or len(obj) != 7:
        return False
    for entry in obj:
        if not isinstance(entry, list) or len(entry) != 2:
            return False
        day, hours = entry[0], entry[1]
        if not isinstance(day, int) or isinstance(day, bool) or not (0 <= day <= 6):
            return False
        if not isinstance(hours, list) or not (12 <= len(hours) <= 24):
            return False
        if any(not isinstance(h, int) or isinstance(h, bool) or not (0 <= h <= 100) for h in hours):
            return False
    return True


def _extract_popular_times(blobs: list[Any]) -> list[dict[str, Any]]:
    """Extract popular-times data from decoded blobs, if present."""
    for blob in blobs:
        for obj in _iter_values(blob):
            if not _looks_like_popular_times(obj):
                continue
            return [
                {
                    "day": _DAY_NAMES[entry[0] % 7],
                    "day_index": entry[0],
                    "hours": list(entry[1]),
                }
                for entry in obj
            ]
    return []


# ── Public API (never raises) ────────────────────────────────────────────
def _place_url(place_id: str) -> str:
    """Build a Google Maps place page URL from a CID / hex / slug place_id."""
    pid = place_id.strip()
    m = re.fullmatch(r"0x[0-9a-f]+:0x([0-9a-f]+)", pid, re.IGNORECASE)
    if m:
        try:
            return GOOGLE_MAPS_CID.format(cid=str(int(m.group(1), 16)))
        except ValueError:
            pass
    if pid.isdigit():
        return GOOGLE_MAPS_CID.format(cid=pid)
    return GOOGLE_MAPS_PLACE.format(slug=quote(pid))


def _extract_place_detail(html: str, blobs: list[Any]) -> dict[str, Any]:
    """Best-effort place-detail record from a place page."""
    for item in _jsonld_items(html):
        rec = _record_from_jsonld(item)
        if rec.get("name"):
            return rec
    records = _blob_records(blobs)
    if records:
        return records[0]
    return {}


async def search_places(query: str, location: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Google Maps business search. Never raises; [] on any failure."""
    try:
        q = f"{query} {location}".strip()
        if not q:
            return []
        cache_key = f"search:{q.lower()}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return list(cached)[:limit]
        url = GOOGLE_MAPS_SEARCH.format(query=quote(q))
        if not await _robots_allowed(url):
            return []
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            return []
        records = _parse_search_results(resp.text)
        if not records and _is_anti_bot(resp.text):
            logger.warning(
                "google_maps_anti_bot",
                extra={
                    "query": q,
                    "hint": "requires repo browser/stealth tier (camoufox/stealth_engine)",
                },
            )
        _cache_set(cache_key, records)
        return list(records)[:limit]
    except Exception:  # public API boundary: never-raise contract
        logger.exception("search_places_failed")
        return []


async def get_place(place_id: str) -> dict[str, Any]:
    """Google Maps place detail (+ popular_times). Never raises; {} on failure."""
    try:
        pid = str(place_id or "").strip()
        if not pid:
            return {}
        url = _place_url(pid)
        if not await _robots_allowed(url):
            return {}
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            return {}
        html = resp.text
        blobs = _extract_blobs(html)
        record = _extract_place_detail(html, blobs)
        if not record:
            if _is_anti_bot(html):
                logger.warning(
                    "google_maps_anti_bot",
                    extra={"place_id": pid, "hint": "requires repo browser/stealth tier"},
                )
            return {}
        popular = _extract_popular_times(blobs)
        if popular:
            record["popular_times"] = popular
        record["source"] = "google"
        return record
    except Exception:  # public API boundary: never-raise contract
        logger.exception("get_place_failed")
        return {}
