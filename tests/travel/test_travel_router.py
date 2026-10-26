"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
import pytest
from fastapi import FastAPI

import datasets.travel.flights as flights
from tests.travel._travel_support import _client, _hermetic_travel, travel_app  # noqa: F401

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


def test_router_importable() -> None:
    import datasets.travel as travel
    import pry.api.routers.data.travel

    assert hasattr(travel, "search_flights")
    assert hasattr(travel, "cheapest_date_grid")
    assert hasattr(travel, "get_hotel_rates")
    assert hasattr(pry.api.routers.data.travel, "router")


def test_router_flights_grid_success(travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_grid(origin: str, dest: str, start_date: str, end_date: str) -> list[dict]:
        return [
            {
                "date": start_date,
                "price": 250,
                "airline": "Delta",
                "duration": 420,
                "stops": 0,
            }
        ]

    monkeypatch.setattr(flights, "cheapest_date_grid", fake_grid)
    resp = _client(travel_app).get(
        "/v1/travel/flights/grid",
        params={
            "origin": "JFK",
            "dest": "CDG",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["date"] == "2026-09-01"
    assert body["origin"] == "JFK"
    assert body["dest"] == "CDG"


def test_router_flights_search_success(
    travel_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        return [{"date": date, "price": 540, "airline": "Air France", "duration": 470, "stops": 1}]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    resp = _client(travel_app).get(
        "/v1/travel/flights/search",
        params={"origin": "JFK", "dest": "CDG", "date": "2026-09-15", "limit": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["price"] == 540
    assert body["limit"] == 5
