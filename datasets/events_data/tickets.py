"""Event-tickets data: Ticketmaster discovery + resale price tracking.

Aggregates live event, ticket, resale-listing and price-history data for
Pry:

* **Ticketmaster Discovery API** — the official free-tier discovery feed
  (``app.ticketmaster.com/discovery/v2``). Requires a free API key via the
  ``PRY_TICKETMASTER_API_KEY`` env var (https://developer.ticketmaster.com).
  Without a key every Ticketmaster call degrades to ``[]`` / ``{}``.
* **Fallback scrape** — Ticketmaster public search pages (JSON-LD). The
  site serves a JS-heavy page to non-browser clients, so the fallback
  frequently yields nothing; treat results as best-effort.
* **Resale listings (StubHub / SeatGeek)** — best-effort scrape of public
  search pages. Both marketplaces sit behind Cloudflare / JS challenges for
  datacenter traffic, so in practice ``get_resale_prices`` usually returns
  ``[]`` — this is flagged honestly rather than faked.
* **Price history** — in-memory tracker (optionally persisted to JSON via
  the ``PRY_TICKETS_HISTORY_JSON`` env var) recording per-event snapshots
  of min/avg resale price and face value, for drop-alert monitoring.

Contract
--------
* :func:`search_events` — async, never raises, returns a ``list`` (``[]``
  on failure).
* :func:`get_event` — async, never raises, returns a ``dict`` (``{}`` on
  failure).
* :func:`get_resale_prices` — async, never raises, returns a ``list``
  (``[]`` on failure / anti-bot blocks).
* :func:`get_price_history` — async, never raises, returns a ``list``
  (``[]`` when nothing tracked).
* :func:`record_price_snapshot` — async, never raises, appends a history
  entry for an event (used by drop-alert pollers to build the series).

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
import os
import re
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_TM_SEARCH_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_TM_EVENT_URL = "https://app.ticketmaster.com/discovery/v2/events/{event_id}.json"
_TM_SEARCH_PAGE_URL = "https://www.ticketmaster.com/search?q={q}"
_SG_SEARCH_URL = "https://seatgeek.com/search?q={q}"
_SH_SEARCH_URL = "https://www.stubhub.com/search?q={q}"

_TM_KEY_ENV = "PRY_TICKETMASTER_API_KEY"
_HISTORY_JSON_ENV = "PRY_TICKETS_HISTORY_JSON"

_MAX_LIMIT = 100  # Ticketmaster Discovery 'size' cap
_MAX_HISTORY_PER_EVENT = 200

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

_JSON_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)

# ── price history store ────────────────────────────────────────────────
# event_id -> ordered snapshots [{date, min_resale, avg_resale, face_value}]
_HISTORY: dict[str, list[dict[str, Any]]] = {}
_LOCK = threading.RLock()


# ── low-level helpers ──────────────────────────────────────────────────


def _tm_api_key() -> str:
    """Return the configured Ticketmaster Discovery key, or '' when missing."""
    return os.environ.get(_TM_KEY_ENV, "").strip()


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(query: str) -> str:
    return quote(query, safe="")


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    if attempt <= 0 or RETRY_BASE <= 0 or MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(MAX_BACKOFF, RETRY_BASE * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
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
    logger.warning("events_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(value: Any) -> int | None:
    """Coerce a JSON/text value to int; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _parse_json_ld(raw: str) -> list[dict[str, Any]]:
    """Parse every JSON-LD block in an HTML page into dicts."""
    out: list[dict[str, Any]] = []
    for match in _JSON_LD_RE.finditer(raw):
        text = match.group(1).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))
    return out


# ── Ticketmaster Discovery API ─────────────────────────────────────────


def _first_genre(ev: dict[str, Any]) -> str:
    """Best-effort genre from a Ticketmaster classification list."""
    classifications = ev.get("classifications")
    if not isinstance(classifications, list):
        return ""
    for cls in classifications:
        if not isinstance(cls, dict):
            continue
        genre_obj = cls.get("genre")
        if isinstance(genre_obj, dict) and genre_obj.get("name"):
            return str(genre_obj["name"])
    for cls in classifications:
        if not isinstance(cls, dict):
            continue
        segment = cls.get("segment")
        if isinstance(segment, dict) and segment.get("name"):
            return str(segment["name"])
    return ""


def _map_tm_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Map one Ticketmaster Discovery ``_embedded.events[]`` record.

    Canonical search shape: ``{id, name, venue, date, genre, min_price,
    max_price, url}``. Returns ``{}`` when the record carries neither an id
    nor a name.
    """
    event_id = str(ev.get("id") or "")
    name = str(ev.get("name") or "")
    if not event_id and not name:
        return {}
    embedded = ev.get("_embedded")
    venue = ""
    if isinstance(embedded, dict):
        venues = embedded.get("venues")
        if isinstance(venues, list) and venues and isinstance(venues[0], dict):
            venue = str(venues[0].get("name") or "")
    dates = ev.get("dates")
    date = ""
    if isinstance(dates, dict):
        start = dates.get("start")
        if isinstance(start, dict):
            date = str(start.get("localDate") or start.get("dateTime") or "")
    genre = _first_genre(ev)
    price_ranges = ev.get("priceRanges")
    lo: list[float] = []
    hi: list[float] = []
    if isinstance(price_ranges, list):
        for pr in price_ranges:
            if not isinstance(pr, dict):
                continue
            minimum = _to_float(pr.get("min"))
            maximum = _to_float(pr.get("max"))
            if minimum is not None:
                lo.append(minimum)
            if maximum is not None:
                hi.append(maximum)
    return {
        "id": event_id,
        "name": name,
        "venue": venue,
        "date": date,
        "genre": genre,
        "min_price": min(lo) if lo else None,
        "max_price": max(hi) if hi else None,
        "url": str(ev.get("url") or ""),
    }


def _map_tm_detail(ev: dict[str, Any]) -> dict[str, Any]:
    """Map a Ticketmaster Discovery event-detail object.

    Canonical detail shape: ``{id, name, venue, date, genre, ticket_status,
    price_ranges, on_sale, url}``.
    """
    record = _map_tm_event(ev)
    if not record:
        return {}
    dates = ev.get("dates")
    ticket_status = "unknown"
    on_sale = False
    if isinstance(dates, dict):
        status = dates.get("status")
        if isinstance(status, dict) and status.get("code"):
            ticket_status = str(status["code"]).lower()
            on_sale = ticket_status in {"onsale", "on_sale"}
    price_ranges: list[dict[str, Any]] = []
    raw_ranges = ev.get("priceRanges")
    if isinstance(raw_ranges, list):
        for pr in raw_ranges:
            if not isinstance(pr, dict):
                continue
            currency = pr.get("currency")
            price_ranges.append(
                {
                    "type": str(pr.get("type") or "standard"),
                    "min": _to_float(pr.get("min")),
                    "max": _to_float(pr.get("max")),
                    "currency": currency if isinstance(currency, str) else None,
                }
            )
    return {
        **record,
        "ticket_status": ticket_status,
        "price_ranges": price_ranges,
        "on_sale": on_sale,
    }


def _parse_tm_search(raw: str) -> list[dict[str, Any]]:
    """Parse the Discovery ``events.json`` search payload."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    embedded = data.get("_embedded")
    if not isinstance(embedded, dict):
        return []
    events = embedded.get("events")
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        record = _map_tm_event(ev)
        if record:
            out.append(record)
    return out


# ── page-scrape fallbacks (Ticketmaster search / resale marketplaces) ──


def _map_jsonld_event(obj: dict[str, Any]) -> dict[str, Any]:
    """Map a JSON-LD Event onto the canonical search record."""
    name = str(obj.get("name") or "")
    if not name:
        return {}
    event_id = str(obj.get("@id") or obj.get("id") or "")
    location = obj.get("location")
    venue = ""
    if isinstance(location, dict):
        venue = str(location.get("name") or "")
    date = str(obj.get("startDate") or obj.get("startTime") or "")
    offers = obj.get("offers")
    lo: float | None = None
    hi: float | None = None
    if isinstance(offers, dict):
        lo = _to_float(offers.get("lowPrice") or offers.get("price"))
        hi = _to_float(offers.get("highPrice") or offers.get("price"))
    elif isinstance(offers, list):
        prices: list[float] = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            parsed = _to_float(offer.get("price"))
            if parsed is not None:
                prices.append(parsed)
        if prices:
            lo, hi = min(prices), max(prices)
    return {
        "id": event_id,
        "name": name,
        "venue": venue,
        "date": date,
        "genre": "",
        "min_price": lo,
        "max_price": hi,
        "url": str(obj.get("url") or ""),
    }


def _parse_page_events(raw: str) -> list[dict[str, Any]]:
    """Extract Event records out of JSON-LD on a Ticketmaster search page."""
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _parse_json_ld(raw):
        for d in _walk_dicts(block):
            name = d.get("name")
            if not isinstance(name, str) or not name:
                continue
            if "@type" not in d and "startDate" not in d and "eventStatus" not in d:
                continue
            record = _map_jsonld_event(d)
            if not record:
                continue
            dedupe_key = record["url"] or record["name"]
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(record)
    return out


def _map_jsonld_listing(marketplace: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    """Map a JSON-LD object with an offer onto a resale listing record."""
    offers = obj.get("offers")
    if isinstance(offers, dict):
        price = _to_float(offers.get("price"))
        quantity = _to_int(offers.get("availableQuantity"))
    elif isinstance(offers, list):
        price = None
        quantity = None
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            candidate = _to_float(offer.get("price"))
            if candidate is not None:
                price = candidate
                quantity = _to_int(offer.get("availableQuantity"))
                break
    else:
        # Bare price objects only count when they carry Event/Product context
        # (the Offer dict itself must not become a separate listing).
        if not isinstance(obj.get("name"), str) or not obj.get("name"):
            return None
        price = _to_float(obj.get("price"))
        quantity = _to_int(obj.get("quantity"))
    if price is None:
        return None
    location = obj.get("location")
    section = ""
    if isinstance(location, dict) and location.get("name"):
        section = str(location["name"])
    if not section:
        section = str(obj.get("section") or "")
    row_value = obj.get("row")
    row = str(row_value) if row_value is not None else ""
    return {
        "marketplace": marketplace,
        "section": section,
        "row": row,
        "listing_price": price,
        "quantity": quantity,
        "last_update": _now_iso(),
    }


def _parse_resale_page(marketplace: str, raw: str) -> list[dict[str, Any]]:
    """Extract resale listings from JSON-LD on a marketplace search page."""
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for block in _parse_json_ld(raw):
        for d in _walk_dicts(block):
            listing = _map_jsonld_listing(marketplace, d)
            if listing:
                out.append(listing)
    return out


# ── price history persistence ──────────────────────────────────────────


def _history_path() -> str:
    """Path of the optional JSON persistence file ('' when disabled)."""
    return os.environ.get(_HISTORY_JSON_ENV, "").strip()


def _load_history() -> None:
    """Reload tracked price history from the JSON persistence file (best effort)."""
    path = _history_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(entries, dict):
        return
    with _LOCK:
        for event_id, snapshots in entries.items():
            if not isinstance(snapshots, list):
                continue
            cleaned = [s for s in snapshots if isinstance(s, dict)]
            _HISTORY[str(event_id)] = cleaned[:_MAX_HISTORY_PER_EVENT]


def _persist_history() -> None:
    """Write the history store to the JSON persistence file (best effort)."""
    path = _history_path()
    if not path:
        return
    try:
        with _LOCK:
            payload = {event_id: list(snapshots) for event_id, snapshots in _HISTORY.items()}
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        logger.debug("events_history_persist_failed", exc_info=True)


_load_history()


def _reset_history() -> None:
    """Drop all in-memory history (tests / ops)."""
    with _LOCK:
        _HISTORY.clear()


# ── public API ─────────────────────────────────────────────────────────


async def search_events(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search upcoming events via Ticketmaster Discovery (+ page fallback).

    Uses the Discovery API when ``PRY_TICKETMASTER_API_KEY`` is set; on a
    missing key, HTTP/parse failure or empty results it falls back to a
    best-effort JSON-LD scrape of the public Ticketmaster search page (which
    is JS-heavy, so often yields ``[]``).

    Async, never raises: returns ``[]`` on any failure.
    """
    text = (query or "").strip()
    bounded = _clamp_limit(limit)
    if not text:
        return []
    key = _tm_api_key()
    if key:
        params = {
            "apikey": key,
            "keyword": text,
            "size": str(bounded),
            "sort": "date,asc",
        }
        raw = await _fetch(_TM_SEARCH_URL, params=params)
        events = _parse_tm_search(raw)
        if events:
            return events[:bounded]
        logger.warning("events_search_api_empty", extra={"query": text[:120]})
    else:
        logger.warning("events_search_no_api_key", extra={"env": _TM_KEY_ENV})
    # Fallback scrape: Ticketmaster public search page (JSON-LD).
    raw = await _fetch(_TM_SEARCH_PAGE_URL.format(q=_url_quote(text)))
    events = _parse_page_events(raw)
    return events[:bounded]


async def get_event(event_id: str) -> dict[str, Any]:
    """Fetch one event's detail from Ticketmaster Discovery. Never raises.

    Requires ``PRY_TICKETMASTER_API_KEY``; returns ``{}`` on missing key,
    HTTP/parse failure or an empty id.
    """
    text = (event_id or "").strip()
    if not text:
        return {}
    key = _tm_api_key()
    if not key:
        logger.warning("events_get_no_api_key", extra={"env": _TM_KEY_ENV})
        return {}
    raw = await _fetch(_TM_EVENT_URL.format(event_id=_url_quote(text)), params={"apikey": key})
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return _map_tm_detail(data)


async def get_resale_prices(event_id: str) -> list[dict[str, Any]]:
    """Search StubHub + SeatGeek for resale listings of an event.

    The resale marketplaces have no public keyless API, so this scrapes
    their public search pages for JSON-LD listing data. Both sites sit
    behind Cloudflare / JS challenges for datacenter traffic — expect
    ``[]`` in practice (flagged honestly, never faked). Uses the event's
    name (from Ticketmaster) to query them.

    Async, never raises: ``[]`` on missing event, anti-bot block, or empty
    page.
    """
    event = await get_event(event_id)
    name = str(event.get("name") or "").strip()
    if not name:
        return []
    out: list[dict[str, Any]] = []
    for marketplace, url in (("stubhub", _SH_SEARCH_URL), ("seatgeek", _SG_SEARCH_URL)):
        raw = await _fetch(url.format(q=_url_quote(name)))
        out.extend(_parse_resale_page(marketplace, raw))
    seen: set[tuple[str, str, str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for listing in out:
        price = listing.get("listing_price")
        if not isinstance(price, (int, float)):
            continue
        key = (
            str(listing.get("marketplace") or ""),
            str(listing.get("section") or ""),
            str(listing.get("row") or ""),
            float(price),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(listing)
    return deduped


async def record_price_snapshot(
    event_id: str,
    min_resale: float | None = None,
    avg_resale: float | None = None,
    face_value: float | None = None,
) -> dict[str, Any]:
    """Record one price-history snapshot for an event. Async, never raises.

    Appends ``{date, min_resale, avg_resale, face_value}`` to the tracked
    series (newest last, capped at ``_MAX_HISTORY_PER_EVENT`` per event) and
    persists when ``PRY_TICKETS_HISTORY_JSON`` is set. Returns
    ``{"event_id", "status": "recorded", "count"}``; ``{"status": "error"}``
    for an empty ``event_id``.
    """
    text = (event_id or "").strip()
    if not text:
        return {"event_id": "", "status": "error", "count": 0}
    snapshot = {
        "date": _now_iso(),
        "min_resale": _to_float(min_resale),
        "avg_resale": _to_float(avg_resale),
        "face_value": _to_float(face_value),
    }
    with _LOCK:
        series = _HISTORY.setdefault(text, [])
        series.append(snapshot)
        if len(series) > _MAX_HISTORY_PER_EVENT:
            del series[: len(series) - _MAX_HISTORY_PER_EVENT]
        count = len(series)
    _persist_history()
    return {"event_id": text, "status": "recorded", "count": count}


async def get_price_history(event_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return tracked price history for an event, newest first. Never raises.

    Returns ``[]`` when nothing has been tracked for the event.
    """
    text = (event_id or "").strip()
    try:
        bounded = max(1, min(int(limit), _MAX_HISTORY_PER_EVENT))
    except (TypeError, ValueError):
        bounded = 100
    with _LOCK:
        series = list(_HISTORY.get(text, []))
    return list(reversed(series))[:bounded]
