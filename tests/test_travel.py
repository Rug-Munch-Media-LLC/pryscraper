# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import routers.travel as travel_router_mod
import travel.flights as flights
import travel.hotels as hotels
from pry.core.errors import PryError
from routers.travel import router as travel_router
from travel.flights import _build_tfs, _extract_af_callbacks, _find_flight_options

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


# ── HTML / JSON fixtures ───────────────────────────────────────────────


def _flights_html() -> str:
    """A Google-Flights-style page with embedded AF_initDataCallback data."""
    data = [
        "search-id",
        [
            [
                ["F:JFK", "F:CDG", 1726416000000, "2026-09-15"],
                [
                    {
                        "price": 612,
                        "airline": "Delta",
                        "duration": 445,
                        "stops": 0,
                        "currency": "USD",
                    },
                    {
                        "price": 540,
                        "airline": "Air France",
                        "duration": 470,
                        "stops": 1,
                        "currency": "USD",
                    },
                ],
            ]
        ],
        "trailing-noise",
    ]
    return (
        "<!DOCTYPE html><html><body>"
        "<script nonce=\"abc\">AF_initDataCallback({key: 'ds:1', hash: 'h1', data: "
        + json.dumps(data)
        + ", sideChannel: {}});</script>"
        "</body></html>"
    )


def _flights_html_parent_child() -> str:
    """Google layout variant: price on parent, airline/duration on child."""
    data = [
        [
            {
                "price": 799,
                "currency": "USD",
                "leg": {"airline": "United", "duration": 380, "stops": 0},
            },
            {
                "price": 855,
                "currency": "USD",
                "leg": {"airline": "Lufthansa", "duration": 495, "stops": 1},
            },
        ]
    ]
    return (
        "<script>AF_initDataCallback({key: 'ds:3', hash: 'h3', data: "
        + json.dumps(data)
        + "});</script>"
    )


def _hotels_google_html() -> str:
    """A Google-Hotels-style page with embedded hotel-rate records."""
    data = [
        "hotel-search",
        [
            {
                "name": "Marriott Marquis New York",
                "price": 189,
                "currency": "USD",
                "total": 378,
                "starRating": 4.0,
            },
            {
                "name": "Hilton Midtown",
                "price": 172,
                "currency": "USD",
                "total": 344,
            },
        ],
    ]
    return (
        "<!DOCTYPE html><html><body>"
        "<script nonce=\"xyz\">AF_initDataCallback({key: 'ds:2', hash: 'h2', data: "
        + json.dumps(data)
        + ", sideChannel: {}});</script>"
        "</body></html>"
    )


def _booking_html() -> str:
    """A Booking.com searchresults page with a data-capla-trace JSON block."""
    payload = {
        "trace": "searchresults",
        "results": [
            {
                "hotel_name": "The Ritz London",
                "price": 420,
                "currency": "GBP",
                "total": 840,
            }
        ],
    }
    block = json.dumps(payload)
    return (
        "<html><body>"
        f'<script type="application/json" data-capla-trace="trace-id">{block}</script>'
        "</body></html>"
    )


def _booking_regex_html() -> str:
    """Booking.com page with no JSON blocks — regex price fallback path."""
    return '<html><body><div data-price="210">Some hotel</div><span>\u20ac180</span></body></html>'


def _kayak_html() -> str:
    """A Kayak hotel page with an embedded ``window.__INITIAL_STATE__``."""
    payload = {
        "data": {
            "hotels": [
                {"name": "The Chelsea Hotel", "price": {"price": 245, "currency": "USD"}},
                {"name": "The Bowery Hotel", "price": {"price": 312, "currency": "USD"}},
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><body>"
        "<script>window.__INITIAL_STATE__ = " + json.dumps(payload) + ";</script>"
        "</body></html>"
    )


def _expedia_html() -> str:
    """An Expedia hotel page with JSON-LD structured data."""
    ld = {
        "@type": "Hotel",
        "name": "Grand Hyatt New York",
        "offers": {"@type": "Offer", "price": 289, "priceCurrency": "USD"},
    }
    return (
        "<!DOCTYPE html><html><head>"
        '<script type="application/ld+json">' + json.dumps(ld) + "</script>"
        "</head><body></body></html>"
    )


# ── tfs encoder ────────────────────────────────────────────────────────


def test_build_tfs_matches_known_good_example() -> None:
    expected = "CBwQAhoeEgoyMDI0LTA1LTI4agcIARIDVFBFcgcIARIDTVlKGh4SCjIwMjQtMDUtMzBqBwgBEgNNWUpyBwgBEgNUUEVAAUgBcAGCAQsI______AZgBAQ"
    got = _build_tfs([("2024-05-28", "TPE", "MYJ"), ("2024-05-30", "MYJ", "TPE")])
    assert got == expected


def test_build_tfs_one_way_structure() -> None:
    import base64

    tfs = _build_tfs([("2026-09-15", "JFK", "CDG")])
    # Header + one leg + fixed tail; starts with the known prefix bytes.
    assert tfs.startswith("CBwQAh")
    # The fixed tail bytes (f16 length-delimited token) survive round-trip.
    padded = tfs.replace("-", "+").replace("_", "/") + "=" * (-len(tfs) % 4)
    raw = base64.b64decode(padded)
    assert raw.endswith(b"\x82\x01\x0b\x08\xff\xff\xff\xff\xf0\x19\x80\x10\x10")


# ── helpers ────────────────────────────────────────────────────────────


def test_valid_date() -> None:
    from travel.flights import _valid_date

    assert _valid_date("2026-09-15") is True
    assert _valid_date("2026-13-01") is False
    assert _valid_date("not-a-date") is False
    assert _valid_date(None) is False  # type: ignore[arg-type]


def test_normalize_code() -> None:
    from travel.flights import _normalize_code

    assert _normalize_code("jfk") == "JFK"
    assert _normalize_code("CDG") == "CDG"
    assert _normalize_code("New York") == ""
    assert _normalize_code("") == ""
    assert _normalize_code(None) == ""  # type: ignore[arg-type]


def test_date_range_bounded() -> None:
    from travel.flights import _date_range

    days = _date_range("2026-09-01", "2026-09-03")
    assert days == ["2026-09-01", "2026-09-02", "2026-09-03"]
    # Reversed range -> empty
    assert _date_range("2026-09-03", "2026-09-01") == []
    # Invalid -> empty
    assert _date_range("bogus", "2026-09-03") == []
    # Long range clamped to _MAX_GRID_DAYS
    long_range = _date_range("2026-01-01", "2026-12-31")
    assert len(long_range) <= flights._MAX_GRID_DAYS


# ── embedded JSON extraction ───────────────────────────────────────────


def test_extract_af_callbacks_parses_single_quoted() -> None:
    callbacks = _extract_af_callbacks(_flights_html())
    assert len(callbacks) == 1
    assert callbacks[0]["key"] == "ds:1"
    assert isinstance(callbacks[0]["data"], list)


def test_extract_af_callbacks_no_callbacks() -> None:
    assert _extract_af_callbacks("<html><body>no data here</body></html>") == []
    assert _extract_af_callbacks("") == []


def test_extract_af_callbacks_skips_malformed() -> None:
    html = (
        "<script>AF_initDataCallback('not-an-object');</script>"
        "<script>AF_initDataCallback({key: 'ds:2', data: [1,2]});</script>"
    )
    callbacks = _extract_af_callbacks(html)
    assert [c["key"] for c in callbacks] == ["ds:2"]


# ── flight option finder ───────────────────────────────────────────────


def test_find_flight_options_single_dict() -> None:
    data = [
        {
            "price": 612,
            "airline": "Delta",
            "duration": 445,
            "stops": 0,
            "currency": "USD",
        },
        {
            "price": 540,
            "airline": "Air France",
            "duration": 470,
            "stops": 1,
            "currency": "USD",
        },
    ]
    options = _find_flight_options(data)
    assert [o["price"] for o in options] == [540, 612]  # sorted ascending
    assert options[0]["airline"] == "Air France"
    assert options[1]["duration"] == 445


def test_find_flight_options_parent_child_merge() -> None:
    data = [
        {
            "price": 799,
            "currency": "USD",
            "leg": {"airline": "United", "duration": 380, "stops": 0},
        }
    ]
    options = _find_flight_options(data)
    assert options == [{"price": 799, "airline": "United", "duration": 380, "stops": 0}]


def test_find_flight_options_dedupes_and_skips_partial() -> None:
    data = [
        {"price": 612, "airline": "Delta", "duration": 445, "stops": 0},
        {"price": 612, "airline": "Delta", "duration": 445, "stops": 0},  # dup
        {"price": 999, "airline": "Delta"},  # no duration -> skipped
        {"price": 300},  # no airline -> skipped
        {"airline": "Delta", "duration": 400},  # no price -> skipped
    ]
    options = _find_flight_options(data)
    assert options == [{"price": 612, "airline": "Delta", "duration": 445, "stops": 0}]


def test_find_flight_options_empty() -> None:
    assert _find_flight_options(None) == []
    assert _find_flight_options({"a": 1}) == []
    assert _find_flight_options("string") == []


def test_extract_duration_from_string() -> None:
    from travel.flights import _extract_duration

    assert _extract_duration({"duration_text": "7 hr 25 min"}) == 445
    assert _extract_duration({"duration_text": "2h 05m"}) == 125
    assert _extract_duration({"duration_text": "Nonstop"}) is None


def test_extract_stops_variants() -> None:
    from travel.flights import _extract_stops

    assert _extract_stops({"stops": 1}) == 1
    assert _extract_stops({"stops_label": "Nonstop"}) == 0
    assert _extract_stops({"stops_label": "2 stops"}) == 2
    assert _extract_stops({"foo": "bar"}) == 0


# ── flights: async / never-raise (mocked HTTP) ─────────────────────────


async def test_search_flights_success() -> None:
    with respx.mock:
        respx.get(url__startswith=_FLIGHTS_URL).mock(
            return_value=httpx.Response(200, text=_flights_html())
        )
        results = await flights.search_flights("JFK", "CDG", "2026-09-15", limit=20)
    assert len(results) == 2
    assert results[0] == {
        "date": "2026-09-15",
        "price": 540,
        "airline": "Air France",
        "duration": 470,
        "stops": 1,
    }
    assert results[1]["airline"] == "Delta"
    assert all(r["date"] == "2026-09-15" for r in results)


async def test_search_flights_parent_child_page() -> None:
    with respx.mock:
        respx.get(url__startswith=_FLIGHTS_URL).mock(
            return_value=httpx.Response(200, text=_flights_html_parent_child())
        )
        results = await flights.search_flights("JFK", "CDG", "2026-09-15")
    assert results[0] == {
        "date": "2026-09-15",
        "price": 799,
        "airline": "United",
        "duration": 380,
        "stops": 0,
    }


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


@respx.mock
async def test_search_flights_rate_limited_never_raises() -> None:
    respx.get(url__startswith=_FLIGHTS_URL).mock(return_value=httpx.Response(429))
    assert await flights.search_flights("JFK", "CDG", "2026-09-15") == []


@respx.mock
async def test_search_flights_bad_html_never_raises() -> None:
    respx.get(url__startswith=_FLIGHTS_URL).mock(
        return_value=httpx.Response(200, text="<html><body>no flights</body></html>")
    )
    assert await flights.search_flights("JFK", "CDG", "2026-09-15") == []


async def test_cheapest_date_grid_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        return [{"date": date, "price": 100, "airline": "Test Air", "duration": 300, "stops": 0}]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    grid = await flights.cheapest_date_grid("JFK", "CDG", "2026-09-01", "2026-09-03")
    assert [g["date"] for g in grid] == ["2026-09-01", "2026-09-02", "2026-09-03"]
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
    assert grid == [
        {"date": "2026-09-01", "price": 200, "airline": "Cheap", "duration": 400, "stops": 1}
    ]


async def test_cheapest_date_grid_skips_failed_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(origin: str, dest: str, date: str, limit: int = 20) -> list[dict]:
        if date == "2026-09-02":
            return []
        return [{"date": date, "price": 100, "airline": "Test Air", "duration": 300, "stops": 0}]

    monkeypatch.setattr(flights, "search_flights", fake_search)
    grid = await flights.cheapest_date_grid("JFK", "CDG", "2026-09-01", "2026-09-03")
    assert [g["date"] for g in grid] == ["2026-09-01", "2026-09-03"]


async def test_cheapest_date_grid_invalid_inputs() -> None:
    assert await flights.cheapest_date_grid("", "CDG", "2026-09-01", "2026-09-03") == []
    assert await flights.cheapest_date_grid("JFK", "CDG", "bogus", "2026-09-03") == []
    assert await flights.cheapest_date_grid("JFK", "CDG", "2026-09-03", "2026-09-01") == []


# ── hotels: booking parser units ───────────────────────────────────────


def test_find_booking_rates_capla_json() -> None:
    rates = hotels._find_booking_rates(_booking_html())
    assert rates == [
        {
            "hotel": "The Ritz London",
            "price_per_night": 420,
            "currency": "GBP",
            "total": 840,
        }
    ]


def test_find_booking_rates_regex_fallback() -> None:
    rates = hotels._find_booking_rates(_booking_regex_html())
    assert rates[0]["price_per_night"] == 210
    assert rates[0]["currency"] == "USD"
    assert rates[1]["price_per_night"] == 180
    assert rates[1]["currency"] == "EUR"
    assert rates[1]["total"] is None


def test_find_booking_rates_empty() -> None:
    assert hotels._find_booking_rates("<html><body>nothing</body></html>") == []


# ── hotels: Kayak / Expedia parsers ───────────────────────────────────


def test_extract_embedded_object_parses_state() -> None:
    data = hotels._extract_embedded_object(_kayak_html(), "window.__INITIAL_STATE__")
    assert data is not None
    assert data["data"]["hotels"][0]["name"] == "The Chelsea Hotel"


def test_extract_embedded_object_missing() -> None:
    assert (
        hotels._extract_embedded_object(
            "<html><body>nothing</body></html>", "window.__INITIAL_STATE__"
        )
        is None
    )
    assert hotels._extract_embedded_object("", "window.__INITIAL_STATE__") is None


def test_find_kayak_rates() -> None:
    data = hotels._extract_embedded_object(_kayak_html(), "window.__INITIAL_STATE__")
    rates = hotels._find_kayak_rates(data)
    assert rates == [
        {"hotel": "The Chelsea Hotel", "price_per_night": 245, "currency": "USD", "total": None},
        {"hotel": "The Bowery Hotel", "price_per_night": 312, "currency": "USD", "total": None},
    ]


def test_find_kayak_rates_empty_and_garbage() -> None:
    assert hotels._find_kayak_rates(None) == []
    assert hotels._find_kayak_rates({"data": [1, 2, 3]}) == []
    assert hotels._find_kayak_rates({"data": {"hotels": [{"name": "No Price"}]}}) == []


def test_extract_json_ld_parses_blocks() -> None:
    blocks = hotels._extract_json_ld(_expedia_html())
    assert len(blocks) == 1
    assert blocks[0]["name"] == "Grand Hyatt New York"


def test_extract_json_ld_skips_malformed() -> None:
    html = (
        '<script type="application/ld+json">not json</script>'
        '<script type="application/ld+json">{"name": "OK"}</script>'
    )
    blocks = hotels._extract_json_ld(html)
    assert [b["name"] for b in blocks] == ["OK"]


def test_find_expedia_rates_json_ld() -> None:
    rates = hotels._find_expedia_rates(_expedia_html())
    assert rates == [
        {"hotel": "Grand Hyatt New York", "price_per_night": 289, "currency": "USD", "total": None}
    ]


def test_find_expedia_rates_empty() -> None:
    assert hotels._find_expedia_rates("<html><body>no ld+json</body></html>") == []


# ── hotels: get_hotel_rates (mocked HTTP) ──────────────────────────────


async def test_get_hotel_rates_google_success() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text=_hotels_google_html())
        )
        result = await hotels.get_hotel_rates("Marriott New York", "2026-09-01", "2026-09-03")
    assert result["hotel"] == "Marriott New York"
    assert result["availability"] == "available"
    assert result["rates"] == [
        {"site": "google", "price_per_night": 172, "currency": "USD", "total": 344}
    ]


async def test_get_hotel_rates_booking_fallback() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_BOOKING_URL).mock(
            return_value=httpx.Response(200, text=_booking_html())
        )
        result = await hotels.get_hotel_rates("Ritz London", "2026-09-01", "2026-09-03")
    assert result["availability"] == "available"
    assert result["rates"] == [
        {"site": "booking", "price_per_night": 420, "currency": "GBP", "total": 840}
    ]


async def test_get_hotel_rates_google_empty_booking_empty_unavailable() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_BOOKING_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_KAYAK_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_EXPEDIA_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        result = await hotels.get_hotel_rates("Nowhere Hotel", "2026-09-01", "2026-09-03")
    assert result["rates"] == []
    assert result["availability"] == "unavailable"


async def test_get_hotel_rates_all_http_fail_unknown() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(return_value=httpx.Response(503))
        respx.get(url__startswith=_HOTELS_BOOKING_URL).mock(return_value=httpx.Response(503))
        respx.get(url__startswith=_HOTELS_KAYAK_URL).mock(return_value=httpx.Response(503))
        respx.get(url__startswith=_HOTELS_EXPEDIA_URL).mock(return_value=httpx.Response(503))
        result = await hotels.get_hotel_rates("Some Hotel", "2026-09-01", "2026-09-03")
    assert result["rates"] == []
    assert result["availability"] == "unknown"


async def test_get_hotel_rates_invalid_inputs() -> None:
    result = await hotels.get_hotel_rates("   ", "2026-09-01", "2026-09-03")
    assert result["rates"] == []
    assert result["availability"] == "unknown"
    result = await hotels.get_hotel_rates("Hotel", "not-a-date", "2026-09-03")
    assert result["rates"] == []
    assert result["availability"] == "unknown"


async def test_get_hotel_rates_kayak_fallback() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_BOOKING_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_KAYAK_URL).mock(
            return_value=httpx.Response(200, text=_kayak_html())
        )
        result = await hotels.get_hotel_rates("Chelsea Hotel", "2026-09-01", "2026-09-03")
    assert result["availability"] == "available"
    assert result["rates"] == [
        {"site": "kayak", "price_per_night": 245, "currency": "USD", "total": None}
    ]


async def test_get_hotel_rates_expedia_fallback_last() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_BOOKING_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_KAYAK_URL).mock(
            return_value=httpx.Response(200, text="<html><body>no hotels</body></html>")
        )
        respx.get(url__startswith=_HOTELS_EXPEDIA_URL).mock(
            return_value=httpx.Response(200, text=_expedia_html())
        )
        result = await hotels.get_hotel_rates("Grand Hyatt", "2026-09-01", "2026-09-03")
    assert result["availability"] == "available"
    assert result["rates"] == [
        {"site": "expedia", "price_per_night": 289, "currency": "USD", "total": None}
    ]


# ── router tests ───────────────────────────────────────────────────────


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


def test_router_importable() -> None:
    import routers.travel
    import travel

    assert hasattr(travel, "search_flights")
    assert hasattr(travel, "cheapest_date_grid")
    assert hasattr(travel, "get_hotel_rates")
    assert hasattr(routers.travel, "router")


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
