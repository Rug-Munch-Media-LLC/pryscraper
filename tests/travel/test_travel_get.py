"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
from tests.travel._travel_support import _hermetic_travel, travel_app  # noqa: F401

import httpx
import respx

import datasets.travel.hotels as hotels
from tests.travel._travel_support import (
    _booking_html,
    _expedia_html,
    _hotels_google_html,
    _kayak_html,
)

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


async def test_get_hotel_rates_google_success() -> None:
    with respx.mock:
        respx.get(url__startswith=_HOTELS_GOOGLE_URL).mock(
            return_value=httpx.Response(200, text=_hotels_google_html())
        )
        result = await hotels.get_hotel_rates("Marriott New York", "2026-09-01", "2026-09-03")
    assert result["hotel"] == "Marriott New York"
    assert result["availability"] == "available"
    expected = [{"site": "google", "price_per_night": 172, "currency": "USD", "total": 344}]
    assert result["rates"] == expected


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
    expected = [{"site": "booking", "price_per_night": 420, "currency": "GBP", "total": 840}]
    assert result["rates"] == expected


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
    expected = [{"site": "kayak", "price_per_night": 245, "currency": "USD", "total": None}]
    assert result["rates"] == expected


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
    expected = [{"site": "expedia", "price_per_night": 289, "currency": "USD", "total": None}]
    assert result["rates"] == expected
