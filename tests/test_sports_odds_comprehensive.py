# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Comprehensive tests for the expanded sports odds engine.

Covers the full coverage matrix: 20+ sports (canonical Odds API keys +
legacy aliases), 12+ canonical books (Pinnacle, DraftKings, FanDuel,
BetMGM, Caesars, PointsBet, BetRivers, bet365, Unibet, William Hill,
Bovada, BetOnline), and all four markets (h2h/moneyline with 3-way draw,
spreads, totals/over-under, outrights/futures). Also covers the
``market`` / ``book`` query params, ``supported_coverage()``, the 10s
in-memory TTL cache on raw upstream responses (and its respx bypass), the
ESPN fallback expansion, and the never-raise contract.

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

import datasets.sports_data.odds as odds
from pry.engine.retry import RetryConfig

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_NFL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
_ODDS_EPL = "https://api.the-odds-api.com/v4/sports/soccer_epl"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_odds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the upstream cache, kill backoff delays, clear the API key."""
    odds._clear_cache()
    monkeypatch.setattr(odds, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _book_payload(books: list[tuple[str, str]]) -> dict[str, Any]:
    """One NBA event with a configurable list of (key, title) bookmakers."""
    return {
        "id": "eid123",
        "sport_key": "basketball_nba",
        "commence_time": "2026-08-17T00:00:00Z",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": key,
                "title": title,
                "last_update": "2026-08-16T18:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": 1.85},
                            {"name": "Los Angeles Lakers", "price": 2.10},
                        ],
                    }
                ],
            }
            for key, title in books
        ],
    }


def _all_books_payload() -> dict[str, Any]:
    """One event priced by all 12 canonical books (Odds API keys)."""
    books = [
        ("pinnacle", "Pinnacle"),
        ("draftkings", "DraftKings"),
        ("fanduel", "FanDuel"),
        ("betmgm", "BetMGM"),
        ("caesars", "Caesars"),
        ("pointsbetus", "PointsBet"),
        ("betrivers", "BetRivers"),
        ("bet365", "Bet365"),
        ("unibet", "Unibet"),
        ("williamhill_us", "William Hill"),
        ("bovada", "Bovada"),
        ("betonlineag", "BetOnline"),
    ]
    return _book_payload(books)


def _multi_market_event() -> dict[str, Any]:
    """One DraftKings event carrying h2h + spreads + totals + outrights."""
    return {
        "id": "eid-multi",
        "sport_key": "basketball_nba",
        "commence_time": "2026-08-17T00:00:00Z",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-16T18:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": 1.85},
                            {"name": "Los Angeles Lakers", "price": 2.10},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": -110, "point": -5.5},
                            {"name": "Boston Celtics", "price": -110, "point": 5.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 224.5},
                            {"name": "Under", "price": -110, "point": 224.5},
                        ],
                    },
                    {
                        "key": "outrights",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 4.5},
                            {"name": "Boston Celtics", "price": 6.0},
                            {"name": "Miami Heat", "price": 12.0},
                        ],
                    },
                ],
            }
        ],
    }


def _soccer_three_way_event() -> dict[str, Any]:
    """A 3-way soccer moneyline with an explicit Draw outcome."""
    return {
        "id": "eid-soccer",
        "sport_key": "soccer_epl",
        "commence_time": "2026-08-17T19:00:00Z",
        "home_team": "Manchester City",
        "away_team": "Liverpool",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "last_update": "2026-08-16T18:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Manchester City", "price": 2.40},
                            {"name": "Draw", "price": 3.40},
                            {"name": "Liverpool", "price": 2.90},
                        ],
                    }
                ],
            }
        ],
    }


def _espn_scoreboard_payload() -> dict[str, Any]:
    """One NBA event on ESPN with moneyline, spread and over/under lines."""
    return {
        "events": [
            {
                "id": "401765432",
                "date": "2026-08-16T00:30:00Z",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "401765432",
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Los Angeles Lakers"},
                                "score": "102",
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Boston Celtics"},
                                "score": "98",
                            },
                        ],
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "details": "LAL -5.5",
                                "overUnder": 224.5,
                                "spread": -5.5,
                                "homeTeamOdds": {"moneyLine": -150, "spreadOdds": -110},
                                "awayTeamOdds": {"moneyLine": 125, "spreadOdds": -110},
                            }
                        ],
                    }
                ],
            }
        ]
    }


# ── supported_coverage() ──────────────────────────────────────────────


def test_supported_coverage_lists_all_sports_books_markets() -> None:
    coverage = odds.supported_coverage()
    required_sports = {
        "americanfootball_nfl",
        "americanfootball_ncaaf",
        "basketball_nba",
        "basketball_ncaab",
        "basketball_wnba",
        "baseball_mlb",
        "icehockey_nhl",
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_italy_serie_a",
        "soccer_uefa_champions_league",
        "tennis_atp",
        "tennis_wta",
        "golf_pga",
        "mma_mixed_martial_arts",
        "boxing",
        "esports_csgo",
        "esports_dota2",
        "esports_league_of_legends",
        "formula_1",
        "cricket_international_t20",
    }
    assert required_sports <= set(coverage["sport_keys"])
    required_books = {
        "pinnacle",
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "pointsbet",
        "betrivers",
        "bet365",
        "unibet",
        "williamhill",
        "bovada",
        "betonline",
    }
    assert required_books <= set(coverage["books"])
    assert set(coverage["markets"]) == {"h2h", "spreads", "totals", "outrights"}
    assert coverage["sources"] == ["the_odds_api", "espn"]
    assert coverage["cache_ttl_seconds"] == 10.0
    assert coverage["api_key_configured"] is False
    # legacy aliases are reported so bots can use short slugs too
    assert coverage["aliases"]["nba"] == "basketball_nba"
    assert coverage["aliases"]["ufc"] == "mma_mixed_martial_arts"


def test_supported_coverage_sport_details() -> None:
    coverage = odds.supported_coverage()
    nba = coverage["sports"]["basketball_nba"]
    assert nba["odds_api_key"] == "basketball_nba"
    assert nba["espn"] == {"sport": "basketball", "league": "nba"}
    assert set(nba["markets"]) == {"h2h", "spreads", "totals", "outrights"}
    # sports without an ESPN feed advertise None so bots can skip them
    assert coverage["sports"]["boxing"]["espn"] is None
    assert coverage["sports"]["esports_csgo"]["espn"] is None
    assert coverage["sports"]["cricket_international_t20"]["espn"] is None
    assert coverage["sports"]["formula_1"]["espn"] == {"sport": "racing", "league": "f1"}


# ── Sport resolution ──────────────────────────────────────────────────


def test_resolve_sports_all_canonical_keys() -> None:
    for key in odds._CANONICAL_SPORTS:
        assert odds._resolve_sports(key) == [key]


def test_resolve_sports_legacy_aliases_and_defaults() -> None:
    assert odds._resolve_sports("nba") == ["nba"]
    assert odds._resolve_sports("ufc") == ["ufc"]
    assert odds._resolve_sports("basketball_nba") == ["basketball_nba"]
    assert odds._resolve_sports("all") == list(odds._DEFAULT_SPORTS)
    assert odds._resolve_sports("") == list(odds._DEFAULT_SPORTS)
    assert odds._resolve_sports("quidditch") == []


@respx.mock
async def test_get_odds_canonical_sport_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_book_payload([("draftkings", "DraftKings")])])
    )
    results = await odds.get_odds(sport="basketball_nba", limit=10)
    assert results
    assert results[0]["sport"] == "basketball_nba"
    results = await odds.get_odds(sport="nba", limit=10)
    assert results
    assert results[0]["sport"] == "nba"


# ── Book coverage & normalization ─────────────────────────────────────


@respx.mock
async def test_all_12_books_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_all_books_payload()])
    )
    results = await odds.get_odds(sport="nba", limit=50)
    assert len(results) == 12
    books = {record["book"] for record in results}
    assert books == {
        "pinnacle",
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "pointsbet",
        "betrivers",
        "bet365",
        "unibet",
        "williamhill",
        "bovada",
        "betonline",
    }
    # each record keeps the upstream title for display (backward compat)
    by_book = {record["book"]: record for record in results}
    assert by_book["draftkings"]["bookmaker"] == "DraftKings"
    assert by_book["williamhill"]["bookmaker"] == "William Hill"
    assert by_book["betonline"]["bookmaker"] == "BetOnline"
    assert by_book["pointsbet"]["bookmaker"] == "PointsBet"


@respx.mock
async def test_book_filter_upstream_and_client_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_all_books_payload()])
    )
    results = await odds.get_odds(sport="nba", limit=50, book="draftkings")
    assert len(results) == 1
    assert results[0]["book"] == "draftkings"
    # The Odds API was asked for just that book upstream too
    assert respx.calls[0].request.url.params["bookmakers"] == "draftkings"


@respx.mock
async def test_book_filter_title_style_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_book_payload([("draftkings", "DraftKings")])])
    )
    results = await odds.get_odds(sport="nba", limit=50, book="DraftKings")
    assert len(results) == 1
    assert results[0]["book"] == "draftkings"


@respx.mock
async def test_book_filter_unknown_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_all_books_payload()])
    )
    assert await odds.get_odds(sport="nba", limit=50, book="shadybook") == []


@respx.mock
async def test_book_filter_espn_fallback() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload())
    )
    results = await odds.get_odds(sport="nba", limit=50, book="draftkings")
    assert len(results) == 1
    assert results[0]["book"] == "draftkings"
    results = await odds.get_odds(sport="nba", limit=50, book="pinnacle")
    assert results == []  # ESPN only carries DraftKings here


# ── Markets ───────────────────────────────────────────────────────────


@respx.mock
async def test_default_market_h2h_backward_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_book_payload([("draftkings", "DraftKings")])])
    )
    results = await odds.get_odds(sport="nba", limit=10)
    assert results[0]["market"] == "h2h"
    assert respx.calls[0].request.url.params["markets"] == "h2h"


@respx.mock
async def test_schema_contract_all_keys_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_book_payload([("draftkings", "DraftKings")])])
    )
    record = (await odds.get_odds(sport="nba", limit=10))[0]
    assert set(record) == {
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
    assert record["book"] == "draftkings"
    assert record["bookmaker"] == "DraftKings"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85
    assert record["draw_odds"] is None
    assert record["spread"] is None
    assert record["total"] is None
    assert record["last_update"] == "2026-08-16T18:00:00Z"
    assert record["source"] == "the_odds_api"


@respx.mock
async def test_draw_odds_three_way_soccer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_EPL).mock(
        return_value=httpx.Response(200, json=[_soccer_three_way_event()])
    )
    results = await odds.get_odds(sport="epl", limit=10)
    assert len(results) == 1
    record = results[0]
    assert record["market"] == "h2h"
    assert record["home_odds"] == 2.40
    assert record["away_odds"] == 2.90
    assert record["draw_odds"] == 3.40


@respx.mock
async def test_market_spreads_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=10, market="spreads")
    assert len(results) == 1
    record = results[0]
    assert record["market"] == "spreads"
    assert record["spread"] == -5.5  # home team's line
    assert record["home_odds"] == -110
    assert record["away_odds"] == -110
    assert respx.calls[0].request.url.params["markets"] == "spreads"


@respx.mock
async def test_market_totals_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=10, market="totals")
    assert len(results) == 1
    record = results[0]
    assert record["market"] == "totals"
    assert record["total"] == 224.5
    assert record["home_odds"] == -110  # Over side
    assert record["away_odds"] == -110  # Under side
    assert respx.calls[0].request.url.params["markets"] == "totals"


@respx.mock
async def test_market_outrights_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=50, market="outrights")
    assert len(results) == 3  # one record per contender
    by_name = {record["home"]: record for record in results}
    assert set(by_name) == {"Los Angeles Lakers", "Boston Celtics", "Miami Heat"}
    assert by_name["Los Angeles Lakers"]["home_odds"] == 4.5
    assert by_name["Miami Heat"]["home_odds"] == 12.0
    assert all(record["market"] == "outrights" for record in results)
    assert respx.calls[0].request.url.params["markets"] == "outrights"


@respx.mock
async def test_market_comma_and_pipe_combos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=50, market="h2h,spreads")
    markets = {record["market"] for record in results}
    assert markets == {"h2h", "spreads"}
    assert respx.calls[0].request.url.params["markets"] == "h2h,spreads"
    results = await odds.get_odds(sport="nba", limit=50, market="h2h|totals|outrights")
    markets = {record["market"] for record in results}
    assert markets == {"h2h", "totals", "outrights"}


@respx.mock
async def test_market_all_and_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=50, market="all")
    assert {record["market"] for record in results} == {"h2h", "spreads", "totals", "outrights"}
    await odds.get_odds(sport="nba", limit=50, market="moneyline")
    assert respx.calls[1].request.url.params["markets"] == "h2h"
    await odds.get_odds(sport="nba", limit=50, market="futures")
    assert respx.calls[2].request.url.params["markets"] == "outrights"
    # unparseable market degrades to the h2h default (never raises)
    await odds.get_odds(sport="nba", limit=50, market="bogus-market")
    assert respx.calls[3].request.url.params["markets"] == "h2h"


# ── ESPN fallback expansion ───────────────────────────────────────────


@respx.mock
async def test_espn_fallback_h2h_default() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload())
    )
    results = await odds.get_odds(sport="nba", limit=10)
    assert len(results) == 1
    record = results[0]
    assert record["market"] == "h2h"
    assert record["book"] == "draftkings"
    assert record["home_odds"] == 1.67  # -150 american -> decimal
    assert record["away_odds"] == 2.25  # +125 american -> decimal
    assert record["source"] == "espn"


@respx.mock
async def test_espn_fallback_spreads_and_totals() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload())
    )
    results = await odds.get_odds(sport="nba", limit=10, market="spreads,totals")
    markets = {record["market"] for record in results}
    assert markets == {"spreads", "totals"}
    spreads = next(r for r in results if r["market"] == "spreads")
    assert spreads["spread"] == -5.5
    assert spreads["home_odds"] == 1.91  # -110 american -> decimal
    totals = next(r for r in results if r["market"] == "totals")
    assert totals["total"] == 224.5


@respx.mock
async def test_espn_fallback_outrights_unsupported_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload())
    )
    assert await odds.get_odds(sport="nba", limit=10, market="outrights") == []


@respx.mock
async def test_espn_fallback_sport_without_espn_returns_empty() -> None:
    # boxing has no ESPN scoreboard feed -> no key configured -> []
    assert await odds.get_odds(sport="boxing", limit=10) == []
    assert respx.calls.call_count == 0


# ── Never-raise contract ──────────────────────────────────────────────


@respx.mock
async def test_http_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(return_value=httpx.Response(500))
    assert await odds.get_odds(sport="nba") == []


@respx.mock
async def test_malformed_payload_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await odds.get_odds(sport="nba") == []


@respx.mock
async def test_invalid_sport_returns_empty() -> None:
    assert await odds.get_odds(sport="quidditch") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_empty_event_id_returns_empty() -> None:
    assert await odds.get_event_odds("") == {}
    assert respx.calls.call_count == 0


# ── get_event_odds ────────────────────────────────────────────────────


@respx.mock
async def test_get_event_odds_comparison_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid-multi").mock(
        return_value=httpx.Response(200, json=_multi_market_event())
    )
    result = await odds.get_event_odds("basketball_nba:eid-multi")
    assert result["sport"] == "basketball_nba"
    assert len(result["bookmakers"]) == 1
    bk = result["bookmakers"][0]
    assert bk["title"] == "DraftKings"
    assert bk["book"] == "draftkings"
    assert bk["markets"][0]["key"] == "h2h"
    assert result["source"] == "the_odds_api"


@respx.mock
async def test_get_event_odds_market_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid-multi").mock(
        return_value=httpx.Response(200, json=_multi_market_event())
    )
    result = await odds.get_event_odds("nba:eid-multi", market="spreads,totals")
    market_keys = [m["key"] for m in result["bookmakers"][0]["markets"]]
    assert market_keys == ["spreads", "totals"]
    assert respx.calls[0].request.url.params["markets"] == "spreads,totals"
    # a filtered-out market is dropped
    result = await odds.get_event_odds("nba:eid-multi", market="h2h")
    assert [m["key"] for m in result["bookmakers"][0]["markets"]] == ["h2h"]


@respx.mock
async def test_get_event_odds_book_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123").mock(
        return_value=httpx.Response(
            200, json=_book_payload([("draftkings", "DraftKings"), ("fanduel", "FanDuel")])
        )
    )
    result = await odds.get_event_odds("nba:eid123", book="fanduel")
    assert len(result["bookmakers"]) == 1
    assert result["bookmakers"][0]["book"] == "fanduel"
    assert respx.calls[0].request.url.params["bookmakers"] == "fanduel"


@respx.mock
async def test_get_event_odds_espn_fallback() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload())
    )
    result = await odds.get_event_odds("401765432")
    assert result["source"] == "espn"
    assert result["event_id"] == "401765432"
    assert result["bookmakers"][0]["book"] == "draftkings"


@respx.mock
async def test_get_event_odds_not_found_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    for base in (_ODDS_NBA, _ODDS_NFL, _ODDS_EPL):
        respx.get(url__startswith=f"{base}/events/nope").mock(return_value=httpx.Response(404))
    assert await odds.get_event_odds("nope") == {}


# ── Cache (10s TTL on raw upstream responses) ─────────────────────────


async def test_cache_enabled_without_respx() -> None:
    assert odds._cache_enabled() is True


@respx.mock
async def test_cache_disabled_while_respx_routes_active() -> None:
    respx.get("https://example.com/cache-probe").mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    assert odds._cache_enabled() is False
    await odds._fetch_json("https://example.com/cache-probe")
    await odds._fetch_json("https://example.com/cache-probe")
    assert len(respx.calls) == 2  # every request observed under mocks


async def test_cache_reuses_response_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return {"events": []}

    monkeypatch.setattr(odds, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/cached")
    await odds._fetch_json("https://example.com/cached")
    assert len(calls) == 1  # second poll served from the 10s cache


async def test_cache_key_distinguishes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append((url, params))
        return {"events": []}

    monkeypatch.setattr(odds, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/x", {"markets": "h2h"})
    await odds._fetch_json("https://example.com/x", {"markets": "spreads"})
    assert len(calls) == 2  # different params -> different cache entries


async def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(odds, "_monotonic", lambda: clock["now"])
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return {"events": []}

    monkeypatch.setattr(odds, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/ttl")
    assert len(calls) == 1
    clock["now"] += 9.0
    await odds._fetch_json("https://example.com/ttl")
    assert len(calls) == 1  # still fresh at 9s
    clock["now"] += 2.0
    await odds._fetch_json("https://example.com/ttl")
    assert len(calls) == 2  # expired at 11s -> refetched


async def test_cache_clear_forces_refetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return {"events": []}

    monkeypatch.setattr(odds, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/cleared")
    odds._clear_cache()
    await odds._fetch_json("https://example.com/cleared")
    assert len(calls) == 2


async def test_cache_not_populated_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return None

    monkeypatch.setattr(odds, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/fail")
    await odds._fetch_json("https://example.com/fail")
    assert len(calls) == 2  # failures are never cached


# ── Backward compatibility ────────────────────────────────────────────


@respx.mock
async def test_get_odds_positional_signature_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_book_payload([("draftkings", "DraftKings")])])
    )
    results = await odds.get_odds("celtics", "nba", 5)
    assert len(results) == 1
    assert results[0]["book"] == "draftkings"


@respx.mock
async def test_event_query_filter_with_new_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(event_query="heat", sport="nba", limit=50, market="outrights")
    assert len(results) == 1  # only the Miami Heat contender matches
    assert results[0]["home"] == "Miami Heat"


@respx.mock
async def test_limit_truncation_with_new_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_multi_market_event()])
    )
    results = await odds.get_odds(sport="nba", limit=2, market="outrights")
    assert len(results) == 2
