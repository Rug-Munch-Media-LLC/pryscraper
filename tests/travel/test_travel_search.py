"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
import httpx
import respx

import datasets.travel.flights as flights
from tests.travel._travel_support import (  # noqa: F401
    _flights_html,
    _flights_html_parent_child,
    _hermetic_travel,
    travel_app,
)

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


async def test_search_flights_success() -> None:
    with respx.mock:
        respx.get(url__startswith=_FLIGHTS_URL).mock(
            return_value=httpx.Response(200, text=_flights_html())
        )
        results = await flights.search_flights("JFK", "CDG", "2026-09-15", limit=20)
    assert len(results) == 2
    expected = {
        "date": "2026-09-15",
        "price": 540,
        "airline": "Air France",
        "duration": 470,
        "stops": 1,
    }
    assert results[0] == expected
    assert results[1]["airline"] == "Delta"
    assert all(r["date"] == "2026-09-15" for r in results)


async def test_search_flights_parent_child_page() -> None:
    with respx.mock:
        respx.get(url__startswith=_FLIGHTS_URL).mock(
            return_value=httpx.Response(200, text=_flights_html_parent_child())
        )
        results = await flights.search_flights("JFK", "CDG", "2026-09-15")
    expected = {
        "date": "2026-09-15",
        "price": 799,
        "airline": "United",
        "duration": 380,
        "stops": 0,
    }
    assert results[0] == expected


async def test_search_flights_limit_applied() -> None:
    with respx.mock:
        respx.get(url__startswith=_FLIGHTS_URL).mock(
            return_value=httpx.Response(200, text=_flights_html())
        )
        results = await flights.search_flights("JFK", "CDG", "2026-09-15", limit=1)
    assert len(results) == 1
    assert results[0]["price"] == 540


async def test_search_flights_invalid_inputs_never_raise() -> None:
    assert await flights.search_flights("", "CDG", "2026-09-15") == []
    assert await flights.search_flights("JFK", "Nope!", "2026-09-15") == []
    assert await flights.search_flights("JFK", "CDG", "not-a-date") == []
    assert await flights.search_flights(None, "CDG", "2026-09-15") == []  # type: ignore[arg-type]


@respx.mock
async def test_search_flights_http_500_never_raises() -> None:
    respx.get(url__startswith=_FLIGHTS_URL).mock(return_value=httpx.Response(500))
    assert await flights.search_flights("JFK", "CDG", "2026-09-15") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_flights_rate_limited_never_raises() -> None:
    respx.get(url__startswith=_FLIGHTS_URL).mock(return_value=httpx.Response(429))
    assert await flights.search_flights("JFK", "CDG", "2026-09-15") == []
    assert respx.calls.call_count == 3


@respx.mock
async def test_search_flights_bad_html_never_raises() -> None:
    respx.get(url__startswith=_FLIGHTS_URL).mock(
        return_value=httpx.Response(200, text="<html><body>no flights</body></html>")
    )
    assert await flights.search_flights("JFK", "CDG", "2026-09-15") == []
    assert respx.calls.call_count == 1
