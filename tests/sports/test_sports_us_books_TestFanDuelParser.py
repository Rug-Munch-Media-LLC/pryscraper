"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support import (
    _fanduel_cache_payload,
    _fanduel_eventgroup_payload,
)


class TestFanDuelParser:
    """FanDuel eventGroup shape -> canonical records."""

    def test_parses_eventgroup_shape(self) -> None:
        records = us._parse_fanduel_eventgroup(
            _fanduel_eventgroup_payload(), "basketball_nba", "fanduel", "FanDuel"
        )
        assert len(records) == 3
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads", "totals"}
        assert set(by_market) == expected

        h2h = by_market["h2h"]
        assert h2h["home"] == "Lakers"
        assert h2h["away"] == "Celtics"
        assert h2h["home_odds"] == 1.56
        assert h2h["away_odds"] == 2.5
        assert h2h["source"] == "us_fanduel"
        assert by_market["spreads"]["spread"] == -5.5
        assert by_market["totals"]["total"] == 224.5

    def test_parses_cache_shape_with_price_ratio(self) -> None:
        records = us._parse_fanduel_eventgroup(
            _fanduel_cache_payload(), "basketball_nba", "fanduel", "FanDuel"
        )
        assert len(records) == 1
        h2h = records[0]
        # 20/23 -> decimal 1 + 20/23 = 1.87 ; 20/11 -> 1 + 20/11 = 2.82
        assert h2h["away_odds"] == 1.87
        assert h2h["home_odds"] == 2.82

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_fanduel_eventgroup(None, "s", "fd", "FD") == []
        assert us._parse_fanduel_eventgroup({}, "s", "fd", "FD") == []
        assert us._parse_fanduel_eventgroup({"events": "nope"}, "s", "fd", "FD") == []
