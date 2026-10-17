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
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.events_data as events_data
import datasets.events_data.tickets as tickets
import pry.api.routers.data.events_data as events_router_mod
from pry.api.routers.data.events_data import router as events_router
from pry.core.errors import PryError

if TYPE_CHECKING:
    from pathlib import Path

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


@respx.mock
async def test_search_events_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_SEARCH_URL).mock(return_value=httpx.Response(200, text=_tm_search_payload()))

    results = await tickets.search_events("test", limit=10)

    assert len(results) == 2
    first = results[0]
    assert first["id"] == "evt-1"
    assert first["name"] == "Test Concert"
    assert first["venue"] == "Madison Square Garden"
    assert first["date"] == "2026-09-01"
    assert first["genre"] == "Rock"
    assert first["min_price"] == 25.0
    assert first["max_price"] == 500.0
    assert first["url"] == "https://www.ticketmaster.com/test-concert"
    expected = {
        "id",
        "name",
        "venue",
        "date",
        "genre",
        "min_price",
        "max_price",
        "url",
    }
    assert set(first) == expected


@respx.mock
async def test_search_events_no_key_uses_page_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "")
    respx.get(url__startswith=_TM_PAGE_URL).mock(
        return_value=httpx.Response(200, text=_tm_page_html())
    )

    results = await tickets.search_events("test")

    assert len(results) == 1
    assert results[0]["name"] == "Scraped Concert"
    assert results[0]["venue"] == "The Beacon Theatre"
    assert results[0]["min_price"] == 99.0
    assert results[0]["max_price"] == 99.0


@respx.mock
async def test_search_events_api_error_falls_back_to_scrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_SEARCH_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_TM_PAGE_URL).mock(
        return_value=httpx.Response(200, text=_tm_page_html())
    )

    results = await tickets.search_events("test")

    assert len(results) == 1
    assert results[0]["name"] == "Scraped Concert"


@respx.mock
async def test_search_events_api_garbage_and_empty_scrape_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_SEARCH_URL).mock(return_value=httpx.Response(200, text="not-json{"))
    respx.get(url__startswith=_TM_PAGE_URL).mock(return_value=httpx.Response(200, text=""))

    assert await tickets.search_events("test") == []


@respx.mock
async def test_search_events_empty_query_no_network() -> None:
    assert await tickets.search_events("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_events_rate_limit_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_SEARCH_URL).mock(return_value=httpx.Response(429))
    respx.get(url__startswith=_TM_PAGE_URL).mock(
        return_value=httpx.Response(200, text=_tm_page_html())
    )

    results = await tickets.search_events("test")

    assert len(results) == 1
    assert results[0]["name"] == "Scraped Concert"


# ── get_event ──────────────────────────────────────────────────────────


@respx.mock
async def test_get_event_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_EVENT_URL).mock(
        return_value=httpx.Response(200, text=json.dumps(_tm_event_dict()))
    )

    detail = await tickets.get_event("evt-1")

    assert detail["id"] == "evt-1"
    assert detail["name"] == "Test Concert"
    assert detail["ticket_status"] == "onsale"
    assert detail["on_sale"] is True
    expected = [
        {"type": "standard", "min": 25.0, "max": 150.0, "currency": "USD"},
        {"type": "premium", "min": 300.0, "max": 500.0, "currency": "USD"},
    ]
    assert detail["price_ranges"] == expected
    assert detail["url"] == "https://www.ticketmaster.com/test-concert"


@respx.mock
async def test_get_event_offsale(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _tm_event_dict()
    payload["dates"] = {"start": {"localDate": "2026-09-01"}, "status": {"code": "offsale"}}
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_EVENT_URL).mock(return_value=httpx.Response(200, text=json.dumps(payload)))

    detail = await tickets.get_event("evt-1")

    assert detail["ticket_status"] == "offsale"
    assert detail["on_sale"] is False


@respx.mock
async def test_get_event_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "")

    assert await tickets.get_event("evt-1") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_event_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_EVENT_URL).mock(return_value=httpx.Response(500))

    assert await tickets.get_event("evt-1") == {}


@respx.mock
async def test_get_event_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")
    respx.get(_TM_EVENT_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))

    assert await tickets.get_event("evt-1") == {}


@respx.mock
async def test_get_event_empty_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tickets, "_tm_api_key", lambda: "test-key")

    assert await tickets.get_event("") == {}
    assert respx.calls.call_count == 0


# ── get_resale_prices ──────────────────────────────────────────────────


@respx.mock
async def test_get_resale_prices_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_event(event_id: str) -> dict[str, Any]:
        return {"id": event_id, "name": "Test Concert"}

    monkeypatch.setattr(tickets, "get_event", fake_get_event)
    respx.get(url__startswith=_SH_SEARCH_URL).mock(
        return_value=httpx.Response(200, text=_resale_html())
    )
    respx.get(url__startswith=_SG_SEARCH_URL).mock(
        return_value=httpx.Response(200, text=_resale_html())
    )

    listings = await tickets.get_resale_prices("evt-1")

    # 2 listings x 2 marketplaces = 4 unique (dedupe key includes marketplace)
    assert len(listings) == 4
    marketplaces = {listing["marketplace"] for listing in listings}
    expected = {"stubhub", "seatgeek"}
    assert marketplaces == expected
    prices = {listing["listing_price"] for listing in listings}
    expected_2 = {85.5, 220.0}
    assert prices == expected_2
    rowed = [listing for listing in listings if listing["row"]]
    assert len(rowed) == 2
    assert rowed[0]["row"] == "A"
    assert rowed[0]["quantity"] == 1
    assert all(listing["last_update"] for listing in listings)


@respx.mock
async def test_get_resale_prices_dedupes_within_marketplace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_event(event_id: str) -> dict[str, Any]:
        return {"id": event_id, "name": "Test Concert"}

    monkeypatch.setattr(tickets, "get_event", fake_get_event)
    respx.get(url__startswith=_SH_SEARCH_URL).mock(
        return_value=httpx.Response(200, text=_resale_html())
    )
    respx.get(url__startswith=_SG_SEARCH_URL).mock(return_value=httpx.Response(200, text=""))

    listings = await tickets.get_resale_prices("evt-1")

    assert len(listings) == 2
    assert all(listing["marketplace"] == "stubhub" for listing in listings)


@respx.mock
async def test_get_resale_prices_anti_bot_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_event(event_id: str) -> dict[str, Any]:
        return {"id": event_id, "name": "Test Concert"}

    monkeypatch.setattr(tickets, "get_event", fake_get_event)
    respx.get(url__startswith=_SH_SEARCH_URL).mock(
        return_value=httpx.Response(200, text="<html><body>challenge</body></html>")
    )
    respx.get(url__startswith=_SG_SEARCH_URL).mock(return_value=httpx.Response(403))

    assert await tickets.get_resale_prices("evt-1") == []


@respx.mock
async def test_get_resale_prices_no_event_name(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_event(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(tickets, "get_event", fake_get_event)

    assert await tickets.get_resale_prices("evt-1") == []
    assert respx.calls.call_count == 0


# ── price history ──────────────────────────────────────────────────────


async def test_record_and_get_price_history() -> None:
    await tickets.record_price_snapshot("evt-1", min_resale=80.0, avg_resale=90.0, face_value=50.0)
    await tickets.record_price_snapshot("evt-1", min_resale=75.0, avg_resale=88.0)

    history = await tickets.get_price_history("evt-1")

    assert len(history) == 2
    assert history[0]["min_resale"] == 75.0  # newest first
    assert history[1]["face_value"] == 50.0
    assert all("date" in entry for entry in history)


async def test_record_price_snapshot_empty_id() -> None:
    result = await tickets.record_price_snapshot("")

    assert result["status"] == "error"
    assert await tickets.get_price_history("") == []


async def test_get_price_history_unknown_event() -> None:
    assert await tickets.get_price_history("nope") == []


async def test_record_price_snapshot_never_raises_on_bad_values() -> None:
    bad_min: Any = "oops"
    bad_face: Any = True
    result = await tickets.record_price_snapshot(
        "evt-1", min_resale=bad_min, avg_resale=None, face_value=bad_face
    )

    assert result["status"] == "recorded"
    assert result["count"] == 1
    history = await tickets.get_price_history("evt-1")
    assert history[0]["min_resale"] is None
    assert history[0]["face_value"] is None


async def test_price_history_caps_per_event() -> None:
    for index in range(tickets._MAX_HISTORY_PER_EVENT + 25):
        await tickets.record_price_snapshot("evt-1", min_resale=float(index))

    history = await tickets.get_price_history("evt-1", limit=500)

    assert len(history) == tickets._MAX_HISTORY_PER_EVENT
    assert history[0]["min_resale"] == float(tickets._MAX_HISTORY_PER_EVENT + 24)


async def test_price_history_json_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.json"
    monkeypatch.setenv(tickets._HISTORY_JSON_ENV, str(path))

    await tickets.record_price_snapshot("evt-1", min_resale=80.0, avg_resale=90.0, face_value=50.0)
    assert path.exists()

    tickets._reset_history()
    tickets._load_history()

    history = await tickets.get_price_history("evt-1")
    assert len(history) == 1
    assert history[0]["min_resale"] == 80.0
    assert history[0]["avg_resale"] == 90.0
    assert history[0]["face_value"] == 50.0


async def test_price_history_load_ignores_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(tickets._HISTORY_JSON_ENV, str(path))
    try:
        tickets._reset_history()
        tickets._load_history()
        assert await tickets.get_price_history("evt-1") == []
    finally:
        monkeypatch.undo()


# ── package + router ───────────────────────────────────────────────────


def test_package_imports() -> None:
    assert hasattr(events_data, "search_events")
    assert hasattr(events_data, "get_event")
    assert hasattr(events_data, "get_resale_prices")
    assert hasattr(events_data, "get_price_history")
    assert hasattr(events_data, "record_price_snapshot")


def test_router_importable() -> None:
    assert hasattr(events_router_mod, "router")
    assert hasattr(events_router_mod, "_events_module")


def test_router_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt-1",
                "name": query,
                "venue": "",
                "date": "",
                "genre": "",
                "min_price": None,
                "max_price": None,
                "url": "",
            }
        ]

    monkeypatch.setattr(tickets, "search_events", fake)
    resp = TestClient(_events_app()).get("/v1/events/search", params={"query": "test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "test"
    assert body["limit"] == 20


def test_router_get_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(event_id: str) -> dict[str, Any]:
        return {"id": event_id, "name": "Test Concert"}

    monkeypatch.setattr(tickets, "get_event", fake)
    resp = TestClient(_events_app()).get("/v1/events/evt-1")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "evt-1"


def test_router_resale_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(event_id: str) -> list[dict[str, Any]]:
        return [
            {
                "marketplace": "seatgeek",
                "section": "112",
                "row": "",
                "listing_price": 85.5,
                "quantity": 2,
                "last_update": "now",
            }
        ]

    monkeypatch.setattr(tickets, "get_resale_prices", fake)
    resp = TestClient(_events_app()).get("/v1/events/evt-1/resale")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["listing_price"] == 85.5


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
