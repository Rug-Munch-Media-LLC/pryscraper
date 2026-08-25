"""Pry — event-tickets data router.

Exposes Ticketmaster event discovery, resale listings (StubHub / SeatGeek)
and tracked resale price history backed by the ``events_data`` subpackage
(built in parallel, so every import is guarded and degrades to 502 while a
module has not landed yet).

Endpoints:
- GET /v1/events/search              — search events (Ticketmaster Discovery
  key via ``PRY_TICKETMASTER_API_KEY``, page-scrape fallback otherwise)
- GET /v1/events/{event_id}          — single event detail
- GET /v1/events/{event_id}/resale   — resale listings (best-effort scrape)
- GET /v1/events/{event_id}/history  — tracked resale price history

This router is NOT wired into api.py yet (the lead wires new routers after
the parallel build lands). It is import-safe standalone.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Events Data"])


def _events_module() -> Any:
    """Import the ``events_data.tickets`` module with a guarded ImportError.

    The module is created in parallel by another agent; return None when it
    has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module("datasets.events_data.tickets")
    except ImportError:
        logger.warning("events_data_module_unavailable")
        return None


def _module_unavailable() -> NoReturn:
    raise ExternalServiceError(
        "events_data.tickets is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/events/search",
    tags=["Events Data"],
    summary="Search events via Ticketmaster Discovery",
)
async def events_search(
    query: str = Query(..., min_length=1, max_length=500, description="Search term"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search upcoming events. Returns a list of event records."""
    mod = _events_module()
    if mod is None:
        _module_unavailable()
    data = await mod.search_events(query, limit=limit)
    return {"success": True, "data": data, "query": query, "limit": limit}


@router.get(
    "/v1/events/{event_id}",
    tags=["Events Data"],
    summary="Get a single event's detail",
)
async def events_get(event_id: str) -> dict[str, Any]:
    """Fetch one event by Ticketmaster Discovery id."""
    mod = _events_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_event(event_id)
    return {"success": True, "data": data, "event_id": event_id}


@router.get(
    "/v1/events/{event_id}/resale",
    tags=["Events Data"],
    summary="Resale listings for an event (StubHub / SeatGeek)",
)
async def events_resale(event_id: str) -> dict[str, Any]:
    """Fetch best-effort resale listings. May be empty (anti-bot)."""
    mod = _events_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_resale_prices(event_id)
    return {"success": True, "data": data, "event_id": event_id}


@router.get(
    "/v1/events/{event_id}/history",
    tags=["Events Data"],
    summary="Tracked resale price history for an event",
)
async def events_history(
    event_id: str,
    limit: int = Query(100, ge=1, le=200, description="Max snapshots (default: 100)"),
) -> dict[str, Any]:
    """Fetch tracked price snapshots (newest first)."""
    mod = _events_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_price_history(event_id, limit=limit)
    return {"success": True, "data": data, "event_id": event_id, "limit": limit}
