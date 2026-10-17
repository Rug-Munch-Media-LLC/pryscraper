# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the direct offshore + European sportsbook scrapers.

Covers ``sports_data.offshore`` (BookMaker-group brands + standalone offshore
books, aggregating the existing Bovada/BetOnline fetchers) and
``sports_data.european`` (Pinnacle guest API, Marathonbet coupon pages, 1xBet
LineFeed, Betfair read-only Exchange API, plus generic embedded/HTML books).

Every book degrades independently and never raises — one dead or geo-blocked
book never blanks the result if another works. All HTTP is mocked with respx
— no live network.
"""

from __future__ import annotations

import base64
import gzip
import json
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
import respx

import datasets.sports_data.european as european
import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from pry.engine import webshare_proxy
from pry.engine.retry import RetryConfig

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)

# ── Representative URL fixtures ─────────────────────────────────────────
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


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset caches, kill backoff delays, clear health + proxy pool."""
    sources._clear_cache()
    offshore._BOOK_HEALTH.clear()
    offshore._BOOK_HEALTH.update(
        {
            book: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book in offshore.OFFSHORE_BOOK_ORDER
        }
    )
    european._BOOK_HEALTH.clear()
    european._BOOK_HEALTH.update(
        {
            book: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book in european.EUROPEAN_BOOK_ORDER
        }
    )
    monkeypatch.setattr(offshore, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(sources, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)
    webshare_proxy.clear_cache()
    webshare_proxy.reset_rotation()


# ── Payload fixtures ────────────────────────────────────────────────────


def _betonline_family_html() -> str:
    """BookMaker-family listing row (shared markup with BetOnline)."""
    return """<html><body>
<div class="game-row">
  <a class="game-link" href="/sportsbook/basketball/nba/game/49000001">Celtics at Lakers</a>
  <span class="team-name away">Boston Celtics</span>
  <span class="team-name home">Los Angeles Lakers</span>
  <span class="moneyline">-118</span>
  <span class="moneyline">+110</span>
</div>
</body></html>"""


def _betonline_family_embedded_html() -> str:
    """BookMaker-family page with a window.__INITIAL_STATE__ JSON blob."""
    state = {
        "games": [
            {
                "gameId": "49000002",
                "awayTeam": "Boston Celtics",
                "homeTeam": "Los Angeles Lakers",
                "wagerCutOff": "2026-08-17T00:00:00Z",
                "gameData": [
                    {
                        "lineType": "AwayLine",
                        "lineDict": {"MoneyLine": {"decimalLine": "1.85"}},
                    },
                    {
                        "lineType": "HomeLine",
                        "lineDict": {"MoneyLine": {"decimalLine": "2.10"}},
                    },
                ],
            }
        ]
    }
    return f"<html><body><script>window.__INITIAL_STATE__ = {json.dumps(state)};</script></body></html>"


def _decimal_rows_html() -> str:
    """Generic SSR decimal-odds row (MyBookie-style standalone book)."""
    return """<html><body>
<div class="game-row">
  <span class="team-name">Boston Celtics</span>
  <span class="team-name">Los Angeles Lakers</span>
  <span class="odds">2.05</span>
  <span class="odds">1.90</span>
</div>
</body></html>"""


def _pinnacle_fixtures_payload() -> dict[str, Any]:
    return {
        "leagues": [
            {
                "id": 6,
                "events": [
                    {
                        "id": 1001,
                        "home": "Los Angeles Lakers",
                        "away": "Boston Celtics",
                        "starts": "2026-08-17T00:00:00Z",
                    }
                ],
            }
        ]
    }


def _pinnacle_odds_payload() -> dict[str, Any]:
    return {
        "leagues": [
            {
                "id": 6,
                "events": [
                    {
                        "id": 1001,
                        "periods": [
                            {
                                "lineId": 9001,
                                "spread": {"hdp": -5.5, "home": "1.91", "away": "1.91"},
                                "moneyline": {"home": "2.10", "away": "1.85"},
                                "total": {"points": 224.5, "over": "1.90", "under": "1.95"},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _marathon_coupon_html() -> str:
    """Marathonbet coupon row (decimal odds, team member links)."""
    return """<html><body>
<div class="coupon-row">
  <a class="member-1" href="/en/betting/Basketball/123">Boston Celtics</a>
  <a class="member-2" href="/en/betting/Basketball/123">Los Angeles Lakers</a>
  <a class="selection-link" href="/en/betting/Basketball/123">2.05</a>
  <a class="selection-link" href="/en/betting/Basketball/123">1.90</a>
</div>
</body></html>"""


def _1xbet_payload() -> dict[str, Any]:
    """1xBet LineFeed envelope: base64(gzip(JSON))."""
    inner = {
        "L": [{"id": 100, "I": "NBA"}],
        "E": [
            {
                "id": 2001,
                "L": 100,
                "S": "2026-08-17T00:00:00Z",
                "T": [{"N": "Boston Celtics"}, {"N": "Los Angeles Lakers"}],
                "G": [
                    {
                        "G": "1",
                        "E": [
                            {"T": "1", "P": {"1": "1.85"}},
                            {"T": "X", "P": {"1": "11.0"}},
                            {"T": "2", "P": {"1": "2.10"}},
                        ],
                    }
                ],
            }
        ],
    }
    raw = base64.b64encode(gzip.compress(json.dumps(inner).encode("utf-8"))).decode("ascii")
    return {"Value": raw}


def _betfair_page_html() -> str:
    return '<html><body><script>var x = {"marketId":"1.200123456"};</script></body></html>'


def _betfair_markets_payload() -> dict[str, Any]:
    return {
        "eventTypes": [
            {
                "eventNodes": [
                    {
                        "event": {"name": "Lakers v Celtics"},
                        "marketNodes": [
                            {
                                "marketId": "1.200123456",
                                "marketName": "Match Odds",
                                "runners": [
                                    {
                                        "runnerName": "Los Angeles Lakers",
                                        "exchange": {"availableToBack": [{"price": 2.10}]},
                                    },
                                    {
                                        "runnerName": "Boston Celtics",
                                        "exchange": {"availableToBack": [{"price": 1.85}]},
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }


def _blocked_html() -> str:
    return "<html><body>Just a moment... checking your browser</body></html>"


def _record(**kw: Any) -> dict[str, Any]:
    """Canonical odds record with sensible defaults."""
    base: dict[str, Any] = {
        "sport": "basketball_nba",
        "event": "Celtics @ Lakers",
        "event_id": "evt-1",
        "market": "h2h",
        "book": "bookmaker",
        "bookmaker": "BookMaker",
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 2.10,
        "away_odds": 1.85,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": None,
        "source": "offshore",
    }
    base.update(kw)
    return base


# ── Registries ──────────────────────────────────────────────────────────


def test_offshore_registry_has_13_books() -> None:
    assert set(offshore.OFFSHORE_BOOKS) == set(offshore.OFFSHORE_BOOK_ORDER)
    assert len(offshore.OFFSHORE_BOOKS) == 13
    for _slug, entry in offshore.OFFSHORE_BOOKS.items():
        assert entry["kind"] in {"family", "embedded"}
        assert 0 <= entry["confidence"] <= 1
        assert entry["base_url"].startswith("https://")


def test_european_registry_has_10_books() -> None:
    assert set(european.EUROPEAN_BOOKS) == set(european.EUROPEAN_BOOK_ORDER)
    assert len(european.EUROPEAN_BOOKS) == 10
    assert set(european.EUROPEAN_BOOKS) >= {"pinnacle", "marathonbet", "1xbet", "betfair"}
    for entry in european.EUROPEAN_BOOKS.values():
        assert entry["kind"] in {"json", "html", "exchange", "embedded"}


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


def test_available_books_before_any_fetch_and_after_failure() -> None:
    # Health starts optimistic (reachable=True), matching sports_data.sources.
    assert set(offshore.available_books()) == set(offshore.OFFSHORE_BOOKS)
    assert set(european.available_books()) == set(european.EUROPEAN_BOOKS)
    european._BOOK_HEALTH["pinnacle"]["reachable"] = False
    assert "pinnacle" not in european.available_books()


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


# ── Offshore: BookMaker-group family books ──────────────────────────────


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


# ── Offshore: standalone books (generic decimal rows) ───────────────────


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


# ── Offshore: geo-block proxy fallback ──────────────────────────────────


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


# ── European: Pinnacle (guest JSON API) ─────────────────────────────────


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


# ── European: Marathonbet (HTML coupon) ─────────────────────────────────


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


# ── European: 1xBet (LineFeed gzip/base64) ──────────────────────────────


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


# ── European: Betfair (read-only exchange API) ──────────────────────────


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


# ── European: generic books ─────────────────────────────────────────────


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


# ── Aggregates ──────────────────────────────────────────────────────────


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


# ── Schema conformance ──────────────────────────────────────────────────


def _schema_keys() -> set[str]:
    return {
        "sport",
        "event",
        "event_id",
        "market",
        "book",
        "bookmaker",
        "home",
        "away",
        "home_odds",
        "away_odds",
        "draw_odds",
        "spread",
        "total",
        "last_update",
        "source",
    }


@respx.mock
async def test_all_records_follow_canonical_schema() -> None:
    respx.get(_BOOKMAKER_NBA).mock(return_value=httpx.Response(200, text=_betonline_family_html()))
    respx.get(_SPORTSBETTING_NBA).mock(
        return_value=httpx.Response(200, text=_betonline_family_embedded_html())
    )
    respx.get(_MYBOOKIE_NBA).mock(return_value=httpx.Response(200, text=_decimal_rows_html()))
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
    offshore_records = await offshore.fetch_offshore_odds("nba")
    european_records = await european.fetch_european_odds("nba")
    for record in [*offshore_records, *european_records]:
        assert set(record) == _schema_keys()
        assert record["sport"] == "basketball_nba"
        assert record["book"]
        assert record["bookmaker"]
        assert record["market"] in {"h2h", "spreads", "totals"}
        assert record["home"]
        assert record["away"]
        assert record["home_odds"] is not None or record["away_odds"] is not None
