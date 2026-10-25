"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support import _dk_eventgroup_payload, _dk_main_array_payload


class TestDraftKingsParser:
    """DraftKings eventgroup shape -> canonical records."""

    def test_parses_all_three_markets(self) -> None:
        records = us._parse_dk_eventgroup(
            _dk_eventgroup_payload(), "basketball_nba", "draftkings", "DraftKings"
        )
        assert len(records) == 3
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads", "totals"}
        assert set(by_market) == expected

        h2h = by_market["h2h"]
        assert h2h["home"] == "Lakers"
        assert h2h["away"] == "Celtics"
        assert h2h["home_odds"] == 1.56  # -180 -> 1.56
        assert h2h["away_odds"] == 2.5  # +150 -> 2.5
        assert h2h["book"] == "draftkings"
        assert h2h["source"] == "us_draftkings"
        assert h2h["event_id"] == "37548622"
        assert h2h["event"] == "Celtics @ Lakers"

        spreads = by_market["spreads"]
        assert spreads["spread"] == -5.5  # home (Lakers) line
        assert spreads["home_odds"] == 1.91

        totals = by_market["totals"]
        assert totals["total"] == 224.5
        assert totals["home_odds"] == 1.91  # Over price
        assert totals["away_odds"] == 1.91  # Under price

    def test_main_array_alternate_shape(self) -> None:
        records = us._parse_dk_eventgroup(
            _dk_main_array_payload(), "basketball_nba", "draftkings", "DraftKings"
        )
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads"}
        assert set(by_market) == expected
        assert by_market["h2h"]["home"] == "Knicks"
        assert by_market["h2h"]["home_odds"] == 1.4  # Knicks -250 -> 1.4
        assert by_market["h2h"]["away_odds"] == 3.0  # Heat +200 -> 3.0

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_dk_eventgroup(None, "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup([], "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup({"groupedMarkets": "nope"}, "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup({"groupedMarkets": [{"event": {}}]}, "s", "dk", "DK") == []
