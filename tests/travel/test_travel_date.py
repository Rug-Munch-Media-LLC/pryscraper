"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
import datasets.travel.flights as flights
from tests.travel._travel_support import _hermetic_travel, travel_app  # noqa: F401

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"

def test_date_range_bounded() -> None:
    from datasets.travel.flights import _date_range

    days = _date_range("2026-09-01", "2026-09-03")
    expected = ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert days == expected
    # Reversed range -> empty
    assert _date_range("2026-09-03", "2026-09-01") == []
    # Invalid -> empty
    assert _date_range("bogus", "2026-09-03") == []
    # Long range clamped to _MAX_GRID_DAYS
    long_range = _date_range("2026-01-01", "2026-12-31")
    assert len(long_range) <= flights._MAX_GRID_DAYS
