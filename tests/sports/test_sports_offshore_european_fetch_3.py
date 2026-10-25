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
import respx

import datasets.sports_data.european as european
import datasets.sports_data.offshore as offshore
from pry.engine.retry import RetryConfig
from tests.sports._sports_offshore_european_support import (
    _1xbet_payload,
    _betfair_page_html,
    _betonline_family_embedded_html,
    _betonline_family_html,
    _marathon_coupon_html,
    _pinnacle_fixtures_payload,
    _pinnacle_odds_payload,
)
from tests.sports._sports_offshore_european_support2 import _betfair_markets_payload

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


@respx.mock
async def test_fetch_offshore_odds_aggregates_reachable_books() -> None:
    respx.get(_BOOKMAKER_NBA).mock(return_value=httpx.Response(200, text=_betonline_family_html()))
    respx.get(_SPORTSBETTING_NBA).mock(
        return_value=httpx.Response(200, text=_betonline_family_embedded_html())
    )
    # Everything else fails quietly (403 catch-all keeps the test hermetic).
    respx.get(url__regex=r"^https://").mock(return_value=httpx.Response(403))
    records = await offshore.fetch_offshore_odds("nba")
    books = {record["book"] for record in records}
    assert "bookmaker" in books
    assert "sportsbetting" in books
    assert all(record["sport"] == "basketball_nba" for record in records)
    for record in records:
        assert record["market"] == "h2h"
        assert record["home_odds"] is not None
        assert record["away_odds"] is not None


@respx.mock
async def test_fetch_offshore_odds_all_fail_returns_empty() -> None:
    respx.get(url__regex=r"^https://").mock(return_value=httpx.Response(403))
    records = await offshore.fetch_offshore_odds("nba")
    assert records == []


@respx.mock
async def test_fetch_european_odds_aggregates_reachable_books() -> None:
    respx.get(_PINNACLE_FIXTURES).mock(
        return_value=httpx.Response(200, json=_pinnacle_fixtures_payload())
    )
    respx.get(_PINNACLE_ODDS).mock(return_value=httpx.Response(200, json=_pinnacle_odds_payload()))
    respx.get(_MARATHON_NBA).mock(return_value=httpx.Response(200, text=_marathon_coupon_html()))
    respx.get(_1XBET_NBA).mock(return_value=httpx.Response(200, json=_1xbet_payload()))
    respx.get(_BETFAIR_PAGE).mock(return_value=httpx.Response(200, text=_betfair_page_html()))
    respx.get(_BETFAIR_MARKETS).mock(
        return_value=httpx.Response(200, json=_betfair_markets_payload())
    )
    respx.get(url__regex=r"^https://").mock(return_value=httpx.Response(403))
    records = await european.fetch_european_odds("nba")
    books = {record["book"] for record in records}
    assert {"pinnacle", "marathonbet", "1xbet", "betfair"} <= books
    assert all(record["source"] == "european" for record in records)


@respx.mock
async def test_fetch_european_odds_never_raises_with_dead_books() -> None:
    respx.get(_PINNACLE_FIXTURES).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(_PINNACLE_ODDS).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(url__regex=r"^https://").mock(return_value=httpx.Response(403))
    records = await european.fetch_european_odds("nba")
    assert records == []


async def test_fetch_offshore_odds_unsupported_sport() -> None:
    records = await offshore.fetch_offshore_odds("quidditch")
    assert records == []


@respx.mock
async def test_fetch_offshore_odds_reuses_bovada_and_betonline() -> None:
    """The aggregate extends (never duplicates) sources' Bovada/BetOnline fetchers."""
    respx.get(
        "https://www.bovada.lv/services/sports/event/v2/events/A/description/basketball/nba"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "path": "sports/event/coupon/events",
                    "events": [
                        {
                            "id": "bov-1",
                            "description": "Boston Celtics at Los Angeles Lakers",
                            "startTime": "2026-08-17T00:00:00Z",
                            "lastModified": "2026-08-16T18:00:00Z",
                            "competitors": [
                                {"id": "c1", "name": "Los Angeles Lakers", "home": True},
                                {"id": "c2", "name": "Boston Celtics", "home": False},
                            ],
                            "displayGroups": [
                                {
                                    "id": "g1",
                                    "description": "Game Lines",
                                    "markets": [
                                        {
                                            "key": "2W-12",
                                            "description": "Moneyline",
                                            "outcomes": [
                                                {
                                                    "type": "H",
                                                    "description": "Los Angeles Lakers",
                                                    "price": {
                                                        "decimal": "2.10",
                                                        "american": "+110",
                                                    },
                                                },
                                                {
                                                    "type": "A",
                                                    "description": "Boston Celtics",
                                                    "price": {
                                                        "decimal": "1.85",
                                                        "american": "-118",
                                                    },
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        )
    )
    respx.get(url__regex=r"^https://").mock(return_value=httpx.Response(403))
    records = await offshore.fetch_offshore_odds("nba")
    bovada = [r for r in records if r["book"] == "bovada"]
    assert bovada
    assert bovada[0]["source"] == "bovada"
    assert bovada[0]["home_odds"] == 2.10
