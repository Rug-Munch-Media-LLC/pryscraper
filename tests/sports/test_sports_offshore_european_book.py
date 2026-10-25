"""Tests for the direct offshore + European sportsbook scrapers.

Covers ``sports_data.offshore`` (BookMaker-group brands + standalone offshore
books, aggregating the existing Bovada/BetOnline fetchers) and
``sports_data.european`` (Pinnacle guest API, Marathonbet coupon pages, 1xBet
LineFeed, Betfair read-only Exchange API, plus generic embedded/HTML books).

Every book degrades independently and never raises — one dead or geo-blocked
book never blanks the result if another works. All HTTP is mocked with respx
— no live network.
"""
from tests.sports._sports_props_injuries_live_support import _hermetic_sports  # noqa: F401
from tests.sports._sports_offshore_european_support import _hermetic  # noqa: F401
from tests.sports._sports_bet_types_support import _hermetic_sports  # noqa: F401
from urllib.parse import urlencode

import httpx
import pytest

import datasets.sports_data.european as european
import datasets.sports_data.offshore as offshore
from pry.engine.retry import RetryConfig

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)
_BOOKMAKER_NBA = "https://www.bookmaker.eu/sportsbook/basketball/nba"
_SPORTSBETTING_NBA = "https://www.sportsbetting.ag/sportsbook/basketball/nba"
_MYBOOKIE_NBA = "https://www.mybookie.ag/sportsbook/basketball/nba"
_HERITAGE_NBA = "https://www.heritage-odds.com/sportsbook/basketball/nba"
_PINNACLE_QUERY = urlencode({"sportId": 6, "isLive": 0, "oddsFormat": "DECIMAL"})
_PINNACLE_FIXTURES = f"https://guest.api.pinnacle.com/v1/fixtures?{_PINNACLE_QUERY}"
_PINNACLE_ODDS = f"https://guest.api.pinnacle.com/v1/odds?{_PINNACLE_QUERY}"
_MARATHON_NBA = "https://www.marathonbet.com/en/betting/Basketball/"
_1XBET_NBA = "https://1xbet.com/service-api/LineFeed/Get1x2_VZip?sport=4&lng=en&tf=2200000&tz=3&mode=4&country=1"
_BETFAIR_PAGE = "https://www.betfair.com/exchange/plus/basketball"
_BETFAIR_QUERY = urlencode(
    {
        "_ak": "nzIFcwyWhrlwYMrh",
        "marketIds": "1.200123456",
        "currencyCode": "USD",
        "locale": "en_GB",
        "rollupLimit": "2",
        "rollupModel": "STAKE",
        "types": (
            "MARKET_STATE,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST,"
            "RUNNER_DESCRIPTION,MARKET_RATES,MARKET_DESCRIPTION,EVENT,RUNNER_METADATA"
        ),
        "alt": "json",
    }
)
_BETFAIR_MARKETS = (
    f"https://www.betfair.com/www/sports/exchange/readonly/v1/bymarket?{_BETFAIR_QUERY}"
)

def test_book_status_shape_and_unknown() -> None:
    status = offshore.book_status()
    assert set(status) == set(offshore.OFFSHORE_BOOKS)
    entry = status["bookmaker"]
    assert entry["name"] == "bookmaker"  # slug key
    assert entry["title"] == "BookMaker"  # display title
    expected = {
        "reachable",
        "blocked",
        "last_checked",
        "latency_ms",
        "error",
    }
    assert set(entry["availability"]) == expected
    assert offshore.book_status("bogus") == {}
    assert european.book_status("bogus") == {}
def test_book_supports() -> None:
    assert offshore.book_supports("bookmaker", "nba")
    assert offshore.book_supports("pinnacle_missing" if False else "mybookie", "nfl")
    assert european.book_supports("pinnacle", "basketball_nba")
    assert european.book_supports("marathonbet", "epl")
    assert not european.book_supports("pinnacle", "quidditch")
    assert not offshore.book_supports("bogus", "nba")
    assert not european.book_supports("bogus", "nba")
def test_book_status_annotates_sibling_registry_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """book_status reuses the sibling BOOKS registry (sports_data.books) when present."""
    if offshore._SIBLING_BOOKS is None:
        monkeypatch.setattr(
            offshore,
            "_SIBLING_BOOKS",
            {
                "bookmaker": {
                    "id": "bookmaker",
                    "name": "BookMaker.eu",
                    "category": "offshore",
                    "method": "html",
                    "geo_required": False,
                }
            },
        )
        monkeypatch.setattr(
            european,
            "_SIBLING_BOOKS",
            {
                "pinnacle": {
                    "id": "pinnacle",
                    "name": "Pinnacle",
                    "category": "eu",
                    "method": "browser",
                    "geo_required": False,
                }
            },
        )
    offshore_entry = offshore.book_status("bookmaker")
    assert offshore_entry["sibling"]["book_id"] == "bookmaker"
    assert offshore_entry["sibling"]["category"] == "offshore"
    european_entry = european.book_status("pinnacle")
    assert european_entry["sibling"]["geo_required"] is False
    # Alias mapping: my slug -> sibling id.
    assert offshore.book_status("sportsbetting")["sibling"]["book_id"] == "sportsbetting-ag"
def test_book_status_degrades_without_sibling_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the sibling registry the status surface still works (no sibling key)."""
    monkeypatch.setattr(offshore, "_SIBLING_BOOKS", None)
    monkeypatch.setattr(european, "_SIBLING_BOOKS", None)
    entry = offshore.book_status("bookmaker")
    assert "sibling" not in entry
    assert entry["title"] == "BookMaker"
    assert european.book_status("pinnacle")["title"] == "Pinnacle"
