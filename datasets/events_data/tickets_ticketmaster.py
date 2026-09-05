"""Ticketmaster Discovery API mapping, parsing and public search/detail calls.

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
import logging
from typing import Any

from datasets.events_data.tickets_common import (
    _TM_EVENT_URL,
    _TM_KEY_ENV,
    _TM_SEARCH_PAGE_URL,
    _TM_SEARCH_URL,
    _clamp_limit,
    _facade,
    _fetch,
    _parse_json_ld,
    _to_float,
    _url_quote,
    _walk_dicts,
)

logger = logging.getLogger(__name__)


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


# ── page-scrape fallback (Ticketmaster public search page) ─────────────


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
    key = _facade()._tm_api_key()
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
    key = _facade()._tm_api_key()
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
