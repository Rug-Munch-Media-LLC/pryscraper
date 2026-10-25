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
import pytest
import respx

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
from tests.sports._sports_offshore_european_support import (
    _betonline_family_embedded_html,
    _betonline_family_html,
    _decimal_rows_html,
    _pinnacle_fixtures_payload,
    _pinnacle_odds_payload,
)
from tests.sports._sports_offshore_european_support2 import _blocked_html


@respx.mock
async def test_fetch_bookmaker_html_happy_path() -> None:
    respx.get(_BOOKMAKER_NBA).mock(return_value=httpx.Response(200, text=_betonline_family_html()))
    records = await offshore.fetch_bookmaker("nba")
    assert len(records) == 1
    record = records[0]
    assert record["source"] == "offshore"
    assert record["book"] == "bookmaker"
    assert record["bookmaker"] == "BookMaker"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 2.10  # +110
    assert record["away_odds"] == 1.85  # -118
    assert offshore.book_status("bookmaker")["availability"]["reachable"] is True
@respx.mock
async def test_fetch_sportsbetting_embedded_json() -> None:
    respx.get(_SPORTSBETTING_NBA).mock(
        return_value=httpx.Response(200, text=_betonline_family_embedded_html())
    )
    records = await offshore.fetch_sportsbetting("nba")
    assert len(records) == 1
    record = records[0]
    assert record["book"] == "sportsbetting"
    assert record["bookmaker"] == "SportsBetting.ag"
    assert record["source"] == "offshore"
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85
    assert record["last_update"] == "2026-08-17T00:00:00Z"
@respx.mock
async def test_fetch_family_book_blocked_flagged() -> None:
    respx.get(_SPORTSBETTING_NBA).mock(return_value=httpx.Response(200, text=_blocked_html()))
    records = await offshore.fetch_sportsbetting("nba")
    assert records == []
    health = offshore.book_status("sportsbetting")["availability"]
    assert health["blocked"] is True
    assert health["reachable"] is False
@respx.mock
async def test_fetch_mybookie_decimal_rows() -> None:
    respx.get(_MYBOOKIE_NBA).mock(return_value=httpx.Response(200, text=_decimal_rows_html()))
    records = await offshore.fetch_mybookie("nba")
    assert len(records) == 1
    record = records[0]
    assert record["book"] == "mybookie"
    assert record["source"] == "offshore"
    assert record["home"] == "Boston Celtics"
    assert record["away"] == "Los Angeles Lakers"
    assert record["home_odds"] == 2.05
    assert record["away_odds"] == 1.90
@respx.mock
async def test_fetch_heritage_js_shell_returns_empty() -> None:
    # A JS-heavy SPA shell has no decimal odds rows -> honest empty, not an error.
    respx.get(_HERITAGE_NBA).mock(
        return_value=httpx.Response(200, text="<html><body><div id='app'></div></body></html>")
    )
    records = await offshore.fetch_heritage("nba")
    assert records == []
    health = offshore.book_status("heritage")["availability"]
    assert health["reachable"] is False
    assert health["error"] == "no odds parsed"
@respx.mock
async def test_fetch_offshore_network_error_never_raises() -> None:
    respx.get(_MYBOOKIE_NBA).mock(side_effect=httpx.ConnectError("boom"))
    records = await offshore.fetch_mybookie("nba")
    assert records == []
async def test_fetch_offshore_unsupported_sport() -> None:
    records = await offshore.fetch_bookmaker("quidditch")
    assert records == []
@respx.mock
async def test_fetch_geo_block_retries_via_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct request blocked -> retried through the Webshare pool -> odds flow."""
    calls = {"count": 0}

    def _side_effect(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, text=_blocked_html())
        return httpx.Response(200, text=_betonline_family_embedded_html())

    respx.get(_SPORTSBETTING_NBA).mock(side_effect=_side_effect)
    monkeypatch.setattr(offshore, "next_webshare_proxy", lambda: "http://user:pass@proxy:8080")
    records = await offshore.fetch_sportsbetting("nba")
    assert len(records) == 1
    assert records[0]["home_odds"] == 2.10
    assert calls["count"] == 2
@respx.mock
async def test_fetch_geo_block_no_proxy_returns_empty() -> None:
    respx.get(_SPORTSBETTING_NBA).mock(return_value=httpx.Response(200, text=_blocked_html()))
    records = await offshore.fetch_sportsbetting("nba")
    assert records == []
    assert offshore.book_status("sportsbetting")["availability"]["blocked"] is True
@respx.mock
async def test_fetch_pinnacle_happy_path() -> None:
    respx.get(_PINNACLE_FIXTURES).mock(
        return_value=httpx.Response(200, json=_pinnacle_fixtures_payload())
    )
    respx.get(_PINNACLE_ODDS).mock(return_value=httpx.Response(200, json=_pinnacle_odds_payload()))
    records = await european.fetch_pinnacle("nba")
    h2h = [r for r in records if r["market"] == "h2h"]
    spreads = [r for r in records if r["market"] == "spreads"]
    totals = [r for r in records if r["market"] == "totals"]
    assert h2h
    assert h2h[0]["book"] == "pinnacle"
    assert h2h[0]["source"] == "european"
    assert h2h[0]["home"] == "Los Angeles Lakers"
    assert h2h[0]["away"] == "Boston Celtics"
    assert h2h[0]["home_odds"] == 2.10
    assert h2h[0]["away_odds"] == 1.85
    assert spreads
    assert spreads[0]["spread"] == -5.5
    assert totals
    assert totals[0]["total"] == 224.5
    assert totals[0]["home_odds"] == 1.90
    assert european.book_status("pinnacle")["availability"]["reachable"] is True
