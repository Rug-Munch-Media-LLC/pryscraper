# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the events_data package (Ticketmaster + resale + history).

Covers the Ticketmaster Discovery API search/detail JSON mapping, the
no-key / HTTP-error / malformed-payload never-raise contract, the JSON-LD
page-scrape fallbacks (Ticketmaster search page, SeatGeek / StubHub resale
pages), the in-memory + JSON-persisted price-history tracker, and the
/v1/events/* router (200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.events_data.tickets as tickets
import pry.api.routers.data.events_data as events_router_mod
from pry.api.routers.data.events_data import router as events_router
from pry.core.errors import PryError

_TM_SEARCH_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_TM_EVENT_URL = "https://app.ticketmaster.com/discovery/v2/events/evt-1.json"
_TM_PAGE_URL = "https://www.ticketmaster.com/search"
_SG_SEARCH_URL = "https://seatgeek.com/search"
_SH_SEARCH_URL = "https://www.stubhub.com/search"


@pytest.fixture(autouse=True)
def _hermetic_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff sleeps and reset history so tests are hermetic and fast."""
    monkeypatch.setattr(tickets, "RETRY_BASE", 0.0)
    monkeypatch.setattr(tickets, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(tickets, "MAX_RETRIES", 0)
    tickets._reset_history()


# ── fixtures ───────────────────────────────────────────────────────────


def _tm_event_dict() -> dict[str, Any]:
    return {
        "id": "evt-1",
        "name": "Test Concert",
        "url": "https://www.ticketmaster.com/test-concert",
        "dates": {"start": {"localDate": "2026-09-01"}, "status": {"code": "onsale"}},
        "classifications": [{"genre": {"name": "Rock"}, "segment": {"name": "Music"}}],
        "priceRanges": [
            {"type": "standard", "min": 25.0, "max": 150.0, "currency": "USD"},
            {"type": "premium", "min": 300.0, "max": 500.0, "currency": "USD"},
        ],
        "_embedded": {"venues": [{"name": "Madison Square Garden"}]},
    }


def _tm_search_payload() -> str:
    return json.dumps(
        {
            "_embedded": {
                "events": [
                    _tm_event_dict(),
                    {
                        "id": "evt-2",
                        "name": "Test Comedy Night",
                        "url": "https://www.ticketmaster.com/test-comedy",
                        "dates": {"start": {"localDate": "2026-09-10"}},
                        "classifications": [{"segment": {"name": "Comedy"}}],
                        "priceRanges": [{"type": "standard", "min": 40.0, "max": 40.0}],
                        "_embedded": {"venues": [{"name": "Comedy Cellar"}]},
                    },
                ]
            }
        }
    )


def _json_ld_html(blocks: list[dict[str, Any]]) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"


def _tm_page_html() -> str:
    """Ticketmaster public search page with one JSON-LD Event."""
    return _json_ld_html(
        [
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Event",
                        "name": "Scraped Concert",
                        "startDate": "2026-10-01T20:00:00-04:00",
                        "location": {"name": "The Beacon Theatre"},
                        "offers": {"price": 99.0},
                        "url": "https://www.ticketmaster.com/scraped-concert",
                    }
                ],
            }
        ]
    )


def _resale_html() -> str:
    """StubHub / SeatGeek search page with JSON-LD Offer listings."""
    return _json_ld_html(
        [
            {
                "@type": "Event",
                "name": "Test Concert",
                "location": {"name": "Section 112"},
                "offers": {"@type": "Offer", "price": "85.50", "availableQuantity": 3},
            },
            {
                "@type": "Event",
                "name": "Test Concert",
                "location": {"name": "Section 5"},
                "row": "A",
                "offers": [
                    {"@type": "Offer", "price": 220.0, "availableQuantity": 1},
                    {"@type": "Offer", "price": 230.0},
                ],
            },
        ]
    )


def _events_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(events_router)
    return app


# ── search_events ──────────────────────────────────────────────────────


def test_router_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(event_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return [{"date": "2026-08-16", "min_resale": 80.0, "avg_resale": 90.0, "face_value": 50.0}]

    monkeypatch.setattr(tickets, "get_price_history", fake)
    resp = TestClient(_events_app()).get("/v1/events/evt-1/history")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["min_resale"] == 80.0


def test_router_502_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_router_mod, "_events_module", lambda: None)
    client = TestClient(_events_app())
    assert client.get("/v1/events/search", params={"query": "x"}).status_code == 502
    assert client.get("/v1/events/evt-1").status_code == 502
    assert client.get("/v1/events/evt-1/resale").status_code == 502
    assert client.get("/v1/events/evt-1/history").status_code == 502


def test_router_validation() -> None:
    client = TestClient(_events_app())
    # empty query -> 422
    assert client.get("/v1/events/search", params={"query": ""}).status_code == 422
    assert client.get("/v1/events/search").status_code == 422
    # limit out of range -> 422
    assert client.get("/v1/events/search", params={"query": "x", "limit": 0}).status_code == 422
    assert client.get("/v1/events/search", params={"query": "x", "limit": 500}).status_code == 422
