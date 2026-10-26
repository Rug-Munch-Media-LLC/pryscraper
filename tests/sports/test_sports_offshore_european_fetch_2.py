"""Tests for the direct offshore + European sportsbook scrapers.

Covers ``sports_data.offshore`` (BookMaker-group brands + standalone offshore
books, aggregating the existing Bovada/BetOnline fetchers) and
``sports_data.european`` (Pinnacle guest API, Marathonbet coupon pages, 1xBet
LineFeed, Betfair read-only Exchange API, plus generic embedded/HTML books).

Every book degrades independently and never raises — one dead or geo-blocked
book never blanks the result if another works. All HTTP is mocked with respx
— no live network.
"""

from urllib.parse import urlencode

import httpx
import respx

import datasets.sports_data.european as european
from pry.engine.retry import RetryConfig
from tests.sports._sports_bet_types_support import _hermetic_sports
from tests.sports._sports_offshore_european_support import (
    _1xbet_payload,
    _betfair_page_html,
    _decimal_rows_html,
    _hermetic,  # noqa: F401
    _marathon_coupon_html,
    _pinnacle_fixtures_payload,
    _pinnacle_odds_payload,
)
from tests.sports._sports_offshore_european_support2 import _betfair_markets_payload, _blocked_html
from tests.sports._sports_props_injuries_live_support import _hermetic_sports  # noqa: F401

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
async def test_fetch_pinnacle_limits_records() -> None:
    respx.get(_PINNACLE_FIXTURES).mock(
        return_value=httpx.Response(200, json=_pinnacle_fixtures_payload())
    )
    respx.get(_PINNACLE_ODDS).mock(return_value=httpx.Response(200, json=_pinnacle_odds_payload()))
    records = await european.fetch_pinnacle("nba", limit=1)
    assert len(records) == 1


@respx.mock
async def test_fetch_pinnacle_error_never_raises() -> None:
    respx.get(_PINNACLE_FIXTURES).mock(return_value=httpx.Response(500))
    respx.get(_PINNACLE_ODDS).mock(return_value=httpx.Response(500))
    records = await european.fetch_pinnacle("nba")
    assert records == []
    assert european.book_status("pinnacle")["availability"]["reachable"] is False


async def test_fetch_pinnacle_unsupported_sport() -> None:
    records = await european.fetch_pinnacle("golf_pga")
    assert records == []


@respx.mock
async def test_fetch_marathonbet_happy_path() -> None:
    respx.get(_MARATHON_NBA).mock(return_value=httpx.Response(200, text=_marathon_coupon_html()))
    records = await european.fetch_marathonbet("nba")
    assert len(records) == 1
    record = records[0]
    assert record["book"] == "marathonbet"
    assert record["bookmaker"] == "Marathonbet"
    assert record["source"] == "european"
    assert record["home_odds"] == 2.05
    assert record["away_odds"] == 1.90


@respx.mock
async def test_fetch_marathonbet_blocked_never_raises() -> None:
    respx.get(_MARATHON_NBA).mock(return_value=httpx.Response(200, text=_blocked_html()))
    records = await european.fetch_marathonbet("nba")
    assert records == []
    assert european.book_status("marathonbet")["availability"]["blocked"] is True


@respx.mock
async def test_fetch_1xbet_happy_path() -> None:
    respx.get(_1XBET_NBA).mock(return_value=httpx.Response(200, json=_1xbet_payload()))
    records = await european.fetch_1xbet("nba")
    assert len(records) == 1
    record = records[0]
    assert record["book"] == "1xbet"
    assert record["source"] == "european"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 1.85
    assert record["away_odds"] == 2.10
    assert record["draw_odds"] == 11.0


@respx.mock
async def test_fetch_1xbet_garbage_payload_never_raises() -> None:
    respx.get(_1XBET_NBA).mock(return_value=httpx.Response(200, json={"Value": "not-base64!!"}))
    records = await european.fetch_1xbet("nba")
    assert records == []


@respx.mock
async def test_fetch_betfair_happy_path() -> None:
    respx.get(_BETFAIR_PAGE).mock(return_value=httpx.Response(200, text=_betfair_page_html()))
    respx.get(_BETFAIR_MARKETS).mock(
        return_value=httpx.Response(200, json=_betfair_markets_payload())
    )
    records = await european.fetch_betfair("nba")
    assert len(records) == 1
    record = records[0]
    assert record["book"] == "betfair"
    assert record["source"] == "european"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85


@respx.mock
async def test_fetch_betfair_no_markets_never_raises() -> None:
    respx.get(_BETFAIR_PAGE).mock(
        return_value=httpx.Response(200, text="<html><body>no markets here</body></html>")
    )
    records = await european.fetch_betfair("nba")
    assert records == []


@respx.mock
async def test_fetch_betfair_page_blocked_flagged() -> None:
    respx.get(_BETFAIR_PAGE).mock(return_value=httpx.Response(403, text=_blocked_html()))
    records = await european.fetch_betfair("nba")
    assert records == []
    assert european.book_status("betfair")["availability"]["blocked"] is True


@respx.mock
async def test_fetch_betway_decimal_rows() -> None:
    url = "https://www.betway.com/en/sports/basketball/nba"
    respx.get(url).mock(return_value=httpx.Response(200, text=_decimal_rows_html()))
    records = await european.fetch_betway("nba")
    assert len(records) == 1
    assert records[0]["book"] == "betway"
    assert records[0]["source"] == "european"
    assert records[0]["home_odds"] == 2.05


@respx.mock
async def test_fetch_sbobet_network_error_never_raises() -> None:
    url = "https://www.sbobet.com/basketball"
    respx.get(url).mock(side_effect=httpx.ConnectError("boom"))
    records = await european.fetch_sbobet("nba")
    assert records == []


async def test_fetch_european_unsupported_sport() -> None:
    records = await european.fetch_betway("quidditch")
    assert records == []
