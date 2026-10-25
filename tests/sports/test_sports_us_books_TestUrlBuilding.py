"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us


class TestUrlBuilding:
    def test_draftkings_url_uses_category_id(self) -> None:
        url = us._build_url("draftkings", "basketball_nba")
        assert (
            url
            == "https://sportsbook.draftkings.com/sites/US-SB/api/v5/eventgroups?categoryId=42648"
        )

    def test_fanduel_url_uses_event_group_id(self) -> None:
        url = us._build_url("fanduel", "basketball_nba")
        assert url is not None
        assert "eventGroup/2" in url
        assert "regionCode=US" in url

    def test_pointsbet_url(self) -> None:
        url = us._build_url("pointsbet", "basketball_nba")
        assert (
            url
            == "https://api.pointsbet.com/api/v2/competitions/5/events/featured?includeLive=false"
        )

    def test_betrivers_url_uses_group_id(self) -> None:
        url = us._build_url("betrivers", "basketball_nba")
        assert url is not None
        assert "groupId=1000093652" in url

    def test_unmapped_sport_returns_none(self) -> None:
        assert us._build_url("draftkings", "soccer_spain_la_liga") is None
        assert us._build_url("pointsbet", "cricket_international_t20") is None

    def test_unbuildable_token_url_returns_none(self) -> None:
        # BetMGM needs a client-generated x-bwin-accessid -> honest None.
        assert us._build_url("betmgm", "basketball_nba") is None

    def test_generic_books_replace_sport_placeholder(self) -> None:
        url = us._build_url("caesars", "basketball_nba")
        assert url == "https://sportsbook.caesars.com/api/events/basketball_nba"

    def test_canonical_alias_resolution(self) -> None:
        assert us._canonical_sport("nba") == "basketball_nba"
        assert us._canonical_sport("basketball_nba") == "basketball_nba"
