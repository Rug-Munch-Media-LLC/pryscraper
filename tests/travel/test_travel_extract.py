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
from datasets.travel.flights import _extract_af_callbacks
from tests.travel._travel_support import _expedia_html, _flights_html, _kayak_html

_FLIGHTS_URL = "https://www.google.com/travel/flights/"
_HOTELS_GOOGLE_URL = "https://www.google.com/travel/hotels"
_HOTELS_BOOKING_URL = "https://www.booking.com/searchresults.html"
_HOTELS_KAYAK_URL = "https://www.kayak.com/hotels"
_HOTELS_EXPEDIA_URL = "https://www.expedia.com/Hotel-Search"


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
    expected = ["ds:2"]
    assert [c["key"] for c in callbacks] == expected


def test_extract_duration_from_string() -> None:
    from datasets.travel.flights import _extract_duration

    assert _extract_duration({"duration_text": "7 hr 25 min"}) == 445
    assert _extract_duration({"duration_text": "2h 05m"}) == 125
    assert _extract_duration({"duration_text": "Nonstop"}) is None


def test_extract_stops_variants() -> None:
    from datasets.travel.flights import _extract_stops

    assert _extract_stops({"stops": 1}) == 1
    assert _extract_stops({"stops_label": "Nonstop"}) == 0
    assert _extract_stops({"stops_label": "2 stops"}) == 2
    assert _extract_stops({"foo": "bar"}) == 0


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
    expected = ["OK"]
    assert [b["name"] for b in blocks] == expected
