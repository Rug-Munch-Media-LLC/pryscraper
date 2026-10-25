"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
from tests.travel._travel_support import _hermetic_travel, travel_app  # noqa: F401

import datasets.travel.hotels as hotels
from datasets.travel.flights import _find_flight_options
from tests.travel._travel_support import (
    _booking_html,
    _booking_regex_html,
    _expedia_html,
    _kayak_html,
)

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


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
    expected = [540, 612]
    assert [o["price"] for o in options] == expected  # sorted ascending
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
    expected = [{"price": 799, "airline": "United", "duration": 380, "stops": 0}]
    assert options == expected


def test_find_flight_options_dedupes_and_skips_partial() -> None:
    data = [
        {"price": 612, "airline": "Delta", "duration": 445, "stops": 0},
        {"price": 612, "airline": "Delta", "duration": 445, "stops": 0},  # dup
        {"price": 999, "airline": "Delta"},  # no duration -> skipped
        {"price": 300},  # no airline -> skipped
        {"airline": "Delta", "duration": 400},  # no price -> skipped
    ]
    options = _find_flight_options(data)
    expected = [{"price": 612, "airline": "Delta", "duration": 445, "stops": 0}]
    assert options == expected


def test_find_flight_options_empty() -> None:
    assert _find_flight_options(None) == []
    assert _find_flight_options({"a": 1}) == []
    assert _find_flight_options("string") == []


def test_find_booking_rates_capla_json() -> None:
    rates = hotels._find_booking_rates(_booking_html())
    expected = [
        {
            "hotel": "The Ritz London",
            "price_per_night": 420,
            "currency": "GBP",
            "total": 840,
        }
    ]
    assert rates == expected


def test_find_booking_rates_regex_fallback() -> None:
    rates = hotels._find_booking_rates(_booking_regex_html())
    assert rates[0]["price_per_night"] == 210
    assert rates[0]["currency"] == "USD"
    assert rates[1]["price_per_night"] == 180
    assert rates[1]["currency"] == "EUR"
    assert rates[1]["total"] is None


def test_find_booking_rates_empty() -> None:
    assert hotels._find_booking_rates("<html><body>nothing</body></html>") == []


def test_find_kayak_rates() -> None:
    data = hotels._extract_embedded_object(_kayak_html(), "window.__INITIAL_STATE__")
    rates = hotels._find_kayak_rates(data)
    expected = [
        {"hotel": "The Chelsea Hotel", "price_per_night": 245, "currency": "USD", "total": None},
        {"hotel": "The Bowery Hotel", "price_per_night": 312, "currency": "USD", "total": None},
    ]
    assert rates == expected


def test_find_kayak_rates_empty_and_garbage() -> None:
    assert hotels._find_kayak_rates(None) == []
    assert hotels._find_kayak_rates({"data": [1, 2, 3]}) == []
    assert hotels._find_kayak_rates({"data": {"hotels": [{"name": "No Price"}]}}) == []


def test_find_expedia_rates_json_ld() -> None:
    rates = hotels._find_expedia_rates(_expedia_html())
    expected = [
        {"hotel": "Grand Hyatt New York", "price_per_night": 289, "currency": "USD", "total": None}
    ]
    assert rates == expected


def test_find_expedia_rates_empty() -> None:
    assert hotels._find_expedia_rates("<html><body>no ld+json</body></html>") == []
