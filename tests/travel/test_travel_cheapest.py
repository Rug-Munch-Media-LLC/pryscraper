"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""

import pytest

import datasets.travel.flights as flights
from tests.travel._travel_support import _hermetic_travel, travel_app  # noqa: F401

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


async def test_cheapest_date_grid_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        return [{"date": date, "price": 100, "airline": "Test Air", "duration": 300, "stops": 0}]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    grid = await flights.cheapest_date_grid("JFK", "CDG", "2026-09-01", "2026-09-03")
    expected = ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert [g["date"] for g in grid] == expected
    assert all(g["price"] == 100 for g in grid)


async def test_cheapest_date_grid_takes_cheapest_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        return [
            {"date": date, "price": 500, "airline": "Expensive", "duration": 300, "stops": 0},
            {"date": date, "price": 200, "airline": "Cheap", "duration": 400, "stops": 1},
        ]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    grid = await flights.cheapest_date_grid("JFK", "CDG", "2026-09-01", "2026-09-01")
    expected = [
        {"date": "2026-09-01", "price": 200, "airline": "Cheap", "duration": 400, "stops": 1}
    ]
    assert grid == expected


async def test_cheapest_date_grid_skips_failed_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        if date == "2026-09-02":
            return []
        return [{"date": date, "price": 100, "airline": "Test Air", "duration": 300, "stops": 0}]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    grid = await flights.cheapest_date_grid("JFK", "CDG", "2026-09-01", "2026-09-03")
    expected = ["2026-09-01", "2026-09-03"]
    assert [g["date"] for g in grid] == expected


async def test_cheapest_date_grid_invalid_inputs() -> None:
    assert await flights.cheapest_date_grid("", "CDG", "2026-09-01", "2026-09-03") == []
    assert await flights.cheapest_date_grid("JFK", "CDG", "bogus", "2026-09-03") == []
    assert await flights.cheapest_date_grid("JFK", "CDG", "2026-09-03", "2026-09-01") == []
