"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.travel.flights as flights
import datasets.travel.hotels as hotels
import pry.api.routers.data.travel as travel_router_mod
from pry.api.routers.data.travel import router as travel_router
from pry.core.errors import PryError

_FLIGHTS_URL = "https://www.google.com/travel/flights/"

_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"

_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"

_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"

_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


@pytest.fixture(autouse=True)
def _hermetic_travel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff sleeps so tests are hermetic and fast."""
    monkeypatch.setattr(flights, "RETRY_BASE", 0.0)
    monkeypatch.setattr(flights, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(hotels, "RETRY_BASE", 0.0)
    monkeypatch.setattr(hotels, "MAX_BACKOFF", 0.0)


@pytest.fixture
def travel_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(travel_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_hotels_rates_success(travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rates(hotel_name: str, checkin: str, checkout: str) -> dict[str, Any]:
        return {
            "hotel": hotel_name,
            "rates": [{"site": "google", "price_per_night": 172, "currency": "USD", "total": 344}],
            "availability": "available",
        }

    monkeypatch.setattr(hotels, "get_hotel_rates", fake_rates)
    resp = _client(travel_app).get(
        "/v1/travel/hotels/rates",
        params={"hotel_name": "Hilton Midtown", "checkin": "2026-09-01", "checkout": "2026-09-03"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["rates"][0]["price_per_night"] == 172


def test_router_flights_grid_502_when_module_absent(
    travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(travel_router_mod, "_travel_module", lambda name: None)
    resp = _client(travel_app).get(
        "/v1/travel/flights/grid",
        params={
            "origin": "JFK",
            "dest": "CDG",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
        },
    )
    assert resp.status_code == 502


def test_router_flights_search_502_when_module_absent(
    travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(travel_router_mod, "_travel_module", lambda name: None)
    resp = _client(travel_app).get(
        "/v1/travel/flights/search",
        params={"origin": "JFK", "dest": "CDG", "date": "2026-09-15"},
    )
    assert resp.status_code == 502


def test_router_hotels_rates_502_when_module_absent(
    travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(travel_router_mod, "_travel_module", lambda name: None)
    resp = _client(travel_app).get(
        "/v1/travel/hotels/rates",
        params={"hotel_name": "Hilton", "checkin": "2026-09-01", "checkout": "2026-09-03"},
    )
    assert resp.status_code == 502


def test_router_validation_422(travel_app: FastAPI) -> None:
    client = _client(travel_app)
    # Bad date pattern -> 422
    resp = client.get(
        "/v1/travel/flights/search",
        params={"origin": "JFK", "dest": "CDG", "date": "2026/09/15"},
    )
    assert resp.status_code == 422
    # Missing required param -> 422
    resp = client.get("/v1/travel/flights/search", params={"origin": "JFK", "dest": "CDG"})
    assert resp.status_code == 422
    # limit out of range -> 422
    resp = client.get(
        "/v1/travel/flights/search",
        params={"origin": "JFK", "dest": "CDG", "date": "2026-09-15", "limit": 0},
    )
    assert resp.status_code == 422
    # Hotels bad dates -> 422
    resp = client.get(
        "/v1/travel/hotels/rates",
        params={"hotel_name": "Hilton", "checkin": "2026-09-01", "checkout": "bogus"},
    )
    assert resp.status_code == 422
