"""Event-tickets data: Ticketmaster discovery + resale price tracking.

Thin facade re-exporting the split modules:

* :mod:`tickets_common` — endpoints, config, fetch/backoff, coercion and
  JSON-LD helpers.
* :mod:`tickets_ticketmaster` — Ticketmaster Discovery mapping/parsing plus
  :func:`search_events` / :func:`get_event`.
* :mod:`tickets_resale` — JSON-LD resale-listing parsing.
* :mod:`tickets_history` — price-history store, persistence and
  :func:`record_price_snapshot` / :func:`get_price_history`.

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

from typing import Any

from datasets.events_data.tickets_common import (  # noqa: F401 (facade re-exports)
    _SG_SEARCH_URL,
    _SH_SEARCH_URL,
    _TM_KEY_ENV,
    MAX_BACKOFF,
    MAX_RETRIES,
    RETRY_BASE,
    _fetch,
    _tm_api_key,
    _url_quote,
)
from datasets.events_data.tickets_history import (  # noqa: F401 (facade re-exports)
    _HISTORY_JSON_ENV,
    _MAX_HISTORY_PER_EVENT,
    _load_history,
    _reset_history,
    get_price_history,
    record_price_snapshot,
)
from datasets.events_data.tickets_resale import _parse_resale_page
from datasets.events_data.tickets_ticketmaster import get_event, search_events

__all__ = [
    "MAX_BACKOFF",
    "MAX_RETRIES",
    "RETRY_BASE",
    "get_event",
    "get_price_history",
    "get_resale_prices",
    "record_price_snapshot",
    "search_events",
]


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


# Load any persisted history once at import (best effort).
_load_history()
