"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support2 import _pointsbet_payload


class TestPointsBetParser:
    """PointsBet featured-events shape -> canonical records."""

    def test_parses_featured_events(self) -> None:
        records = us._parse_pointsbet_events(
            _pointsbet_payload(), "basketball_nba", "pointsbet", "PointsBet"
        )
        assert len(records) == 2
        by_market = {record["market"]: record for record in records}
        assert by_market["h2h"]["home_odds"] == 1.56
        assert by_market["h2h"]["away_odds"] == 2.5
        assert by_market["spreads"]["spread"] == -5.5

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_pointsbet_events("nope", "s", "pb", "PB") == []
        assert us._parse_pointsbet_events({"events": []}, "s", "pb", "PB") == []
