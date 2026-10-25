"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support import _dk_eventgroup_payload
from tests.sports._sports_us_books_support2 import _generic_events_payload


class TestGenericParser:
    """Best-effort parser used by the browser-tier books."""

    def test_parses_events_container(self) -> None:
        records = us._parse_generic_events(
            _generic_events_payload(), "basketball_nba", "espnbet", "ESPN BET"
        )
        assert len(records) == 1
        h2h = records[0]
        assert h2h["home"] == "Knicks"
        assert h2h["away"] == "Heat"
        assert h2h["home_odds"] == 1.4
        assert h2h["book"] == "espnbet"

    def test_never_raises_on_unknown_shapes(self) -> None:
        # A DraftKings payload has no events/fixtures container -> no records.
        assert us._parse_generic_events(_dk_eventgroup_payload(), "s", "x", "X") == []
        assert us._parse_generic_events(None, "s", "x", "X") == []
        assert us._parse_generic_events([], "s", "x", "X") == []
