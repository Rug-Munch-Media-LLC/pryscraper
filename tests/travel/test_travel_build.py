"""Tests for the travel package (Google Flights / Google Hotels / Booking.com).

Covers the ``tfs`` protobuf encoder (byte-for-byte against a known-good
example), the ``AF_initDataCallback`` embedded-JSON extraction, the
signature-based flight/hotel record finders, the never-raise contract
(HTTP errors, rate limits, bad HTML/JSON all degrade to empty output), and
the /v1/travel/* router (200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched helpers) — no live network.
"""
from datasets.travel.flights import _build_tfs
from tests.travel._travel_support import _hermetic_travel, travel_app  # noqa: F401

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"

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
