# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the sports_data package (odds / stats / scores).

Covers The Odds API live-odds fetching + ESPN scoreboard fallback, event
odds comparison (with and without a sport prefix), ESPN player stats
(name search + numeric athlete id + both payload shapes), ESPN scores (date
normalization, all-sport merge), the never-raise contract (HTTP errors and
malformed payloads degrade to empty output), and the /v1/sports/* router
(200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.sports_data as sports_data
import datasets.sports_data.odds as odds
import datasets.sports_data.scores as scores
import datasets.sports_data.stats as stats
import pry.api.routers.data.sports_data as sports_router_mod
from pry.api.routers.data.sports_data import router as sports_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_NFL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
_ODDS_EPL = "https://api.the-odds-api.com/v4/sports/soccer_epl"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_SCORE_NFL = "https://site.api.espn.com/apis/site/v2/sports/americanfootball/nfl/scoreboard"
_SCORE_EPL = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_STATS = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/1966/stats"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the Odds API key so tests are deterministic."""
    monkeypatch.setattr(odds, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(stats, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(scores, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _odds_event_payload() -> dict[str, Any]:
    return {
        "id": "eid123",
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
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "last_update": "2026-08-16T18:05:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": 1.80},
                            {"name": "Los Angeles Lakers", "price": 2.20},
                        ],
                    }
                ],
            },
        ],
    }


def _espn_scoreboard_payload(with_odds: bool = True) -> dict[str, Any]:
    events: list[dict[str, Any]] = [
        {
            "id": "401765432",
            "date": "2026-08-16T00:30:00Z",
            "name": "Celtics at Lakers",
            "competitions": [
                {
                    "id": "401765432",
                    "status": {
                        "type": {"name": "STATUS_FINAL", "description": "Final", "state": "post"}
                    },
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {"displayName": "Los Angeles Lakers", "abbreviation": "LAL"},
                            "score": "102",
                        },
                        {
                            "homeAway": "away",
                            "team": {"displayName": "Boston Celtics", "abbreviation": "BOS"},
                            "score": "98",
                        },
                    ],
                    "odds": (
                        [
                            {
                                "provider": {"name": "DraftKings"},
                                "details": "LAL -5.5",
                                "overUnder": 224.5,
                                "spread": -5.5,
                                "homeTeamOdds": {"moneyLine": -150, "spreadOdds": -110},
                                "awayTeamOdds": {"moneyLine": 125, "spreadOdds": -110},
                            }
                        ]
                        if with_odds
                        else []
                    ),
                }
            ],
        },
        {
            "id": "401765433",
            "date": "2026-08-16T02:30:00Z",
            "name": "Warriors at Suns",
            "competitions": [
                {
                    "id": "401765433",
                    "status": {
                        "type": {
                            "name": "STATUS_IN_PROGRESS",
                            "description": "In Progress",
                            "state": "in",
                        }
                    },
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {"displayName": "Phoenix Suns", "abbreviation": "PHX"},
                            "score": "45",
                        },
                        {
                            "homeAway": "away",
                            "team": {"displayName": "Golden State Warriors", "abbreviation": "GSW"},
                            "score": "50",
                        },
                    ],
                    "odds": [],
                }
            ],
        },
    ]
    return {"events": events}


def _search_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "items": [
            {
                "id": "1966",
                "displayName": "LeBron James",
                "type": "player",
                "sport": "basketball",
                "league": "nba",
                "teamRelationships": [
                    {"type": "team", "displayName": "Los Angeles Lakers", "core": {}}
                ],
            }
        ],
    }


def _stats_payload() -> dict[str, Any]:
    return {
        "teams": {
            "los-angeles-lakers": {
                "id": "13",
                "displayName": "Los Angeles Lakers",
                "abbreviation": "LAL",
            },
        },
        "categories": [
            {
                "name": "averages",
                "displayName": "Regular Season Averages",
                "labels": ["GP", "PTS"],
                "names": ["gamesPlayed", "avgPoints"],
                "displayNames": ["Games Played", "Points Per Game"],
                "descriptions": ["Games played.", "Points per game."],
                "statistics": [
                    {
                        "teamId": "13",
                        "teamSlug": "los-angeles-lakers",
                        "season": {"year": 2025, "displayName": "2024-25"},
                        "stats": ["71", "25.7"],
                        "position": "F",
                    },
                    {
                        "teamId": "13",
                        "teamSlug": "los-angeles-lakers",
                        "season": {"year": 2026, "displayName": "2025-26"},
                        "stats": ["60", "20.9"],
                        "position": "F",
                    },
                ],
                "totals": ["131", "46.6"],
                "sortKey": "averages",
            }
        ],
        "glossary": [],
    }


# ── odds: get_odds — The Odds API path ────────────────────────────────


@respx.mock
async def test_get_odds_odds_api_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_odds_event_payload()])
    )
    results = await odds.get_odds(sport="nba", limit=10)
    assert len(results) == 2  # one record per bookmaker
    assert {record["bookmaker"] for record in results} == {"DraftKings", "FanDuel"}
    by_bookmaker = {record["bookmaker"]: record for record in results}
    record = by_bookmaker["DraftKings"]
    assert record["sport"] == "nba"
    assert record["event"] == "Boston Celtics @ Los Angeles Lakers"
    assert record["event_id"] == "eid123"
    assert record["market"] == "h2h"
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85
    assert record["last_update"] == "2026-08-16T18:00:00Z"
    assert record["source"] == "the_odds_api"
    assert by_bookmaker["FanDuel"]["home_odds"] == 2.20


@respx.mock
async def test_get_odds_odds_api_event_query_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_odds_event_payload()])
    )
    results = await odds.get_odds(event_query="suns", sport="nba", limit=10)
    assert results == []  # no Suns event in the payload
    results = await odds.get_odds(event_query="celtics", sport="nba", limit=10)
    assert len(results) == 2


@respx.mock
async def test_get_odds_odds_api_limit_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_odds_event_payload()])
    )
    results = await odds.get_odds(sport="nba", limit=1)
    assert len(results) == 1


@respx.mock
async def test_get_odds_odds_api_all_merges_default_sports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(
        return_value=httpx.Response(200, json=[_odds_event_payload()])
    )
    respx.get(url__startswith=_ODDS_NFL).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__startswith=_ODDS_EPL).mock(return_value=httpx.Response(200, json=[]))
    results = await odds.get_odds(sport="all", limit=50)
    assert len(results) == 2
    assert all(record["sport"] == "nba" for record in results)


# ── odds: get_odds — ESPN fallback path ───────────────────────────────


@respx.mock
async def test_get_odds_espn_fallback_no_key() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=True))
    )
    results = await odds.get_odds(sport="nba", limit=10)
    assert len(results) == 1  # only the first event has an odds block
    record = results[0]
    assert record["sport"] == "nba"
    assert record["event"] == "Boston Celtics @ Los Angeles Lakers"
    assert record["event_id"] == "401765432"
    assert record["market"] == "h2h"
    assert record["bookmaker"] == "DraftKings"
    assert record["home_odds"] == 1.67  # -150 american -> decimal
    assert record["away_odds"] == 2.25  # +125 american -> decimal
    assert record["source"] == "espn"


@respx.mock
async def test_get_odds_espn_no_odds_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=False))
    )
    assert await odds.get_odds(sport="nba") == []


@respx.mock
async def test_get_odds_http_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(return_value=httpx.Response(500))
    assert await odds.get_odds(sport="nba") == []


@respx.mock
async def test_get_odds_malformed_payload_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_ODDS_NBA).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await odds.get_odds(sport="nba") == []


@respx.mock
async def test_get_odds_invalid_sport_returns_empty() -> None:
    assert await odds.get_odds(sport="quidditch") == []
    assert respx.calls.call_count == 0


# ── odds: get_event_odds ──────────────────────────────────────────────


@respx.mock
async def test_get_event_odds_odds_api_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123").mock(
        return_value=httpx.Response(200, json=_odds_event_payload())
    )
    result = await odds.get_event_odds("nba:eid123")
    assert result["event_id"] == "eid123"
    assert result["sport"] == "nba"
    assert result["event"] == "Boston Celtics @ Los Angeles Lakers"
    assert result["commence_time"] == "2026-08-17T00:00:00Z"
    assert len(result["bookmakers"]) == 2
    assert result["bookmakers"][0]["title"] == "DraftKings"
    assert result["bookmakers"][0]["markets"][0]["key"] == "h2h"
    assert result["source"] == "the_odds_api"


@respx.mock
async def test_get_event_odds_odds_api_scans_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123").mock(
        return_value=httpx.Response(200, json=_odds_event_payload())
    )
    result = await odds.get_event_odds("eid123")
    assert result["sport"] == "nba"  # first default sport wins
    assert respx.calls.call_count == 1  # NFL/EPL never probed


@respx.mock
async def test_get_event_odds_espn_fallback() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=True))
    )
    result = await odds.get_event_odds("401765432")
    assert result["event_id"] == "401765432"
    assert result["sport"] == "nba"
    assert result["source"] == "espn"
    assert len(result["bookmakers"]) == 1
    assert result["bookmakers"][0]["title"] == "DraftKings"


@respx.mock
async def test_get_event_odds_not_found_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    for base in (_ODDS_NBA, _ODDS_NFL, _ODDS_EPL):
        respx.get(url__startswith=f"{base}/events/nope").mock(return_value=httpx.Response(404))
    assert await odds.get_event_odds("nope") == {}


@respx.mock
async def test_get_event_odds_http_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{_ODDS_NFL}/events/eid123").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{_ODDS_EPL}/events/eid123").mock(return_value=httpx.Response(500))
    assert await odds.get_event_odds("eid123") == {}


@respx.mock
async def test_get_event_odds_empty_id_returns_empty() -> None:
    assert await odds.get_event_odds("") == {}
    assert respx.calls.call_count == 0


# ── stats: get_player_stats ───────────────────────────────────────────


@respx.mock
async def test_get_player_stats_success() -> None:
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, json=_search_payload())
    )
    respx.get(url__startswith=_STATS).mock(return_value=httpx.Response(200, json=_stats_payload()))
    result = await stats.get_player_stats("LeBron James", sport="nba")
    assert result["player"] == "LeBron James"
    assert result["sport"] == "nba"
    assert result["team"] == "Los Angeles Lakers"
    assert result["position"] == "F"
    assert result["season"] == "2025-26"
    assert result["stats"] == {"Games Played": "60", "Points Per Game": "20.9"}
    assert result["source"] == "espn"


@respx.mock
async def test_get_player_stats_numeric_id_skips_search() -> None:
    respx.get(url__startswith=_STATS).mock(return_value=httpx.Response(200, json=_stats_payload()))
    result = await stats.get_player_stats("1966", sport="nba")
    assert result["sport"] == "nba"
    assert result["stats"]["Points Per Game"] == "20.9"
    assert respx.calls.call_count == 1  # only the stats endpoint
    assert all(_SEARCH not in str(call.request.url) for call in respx.calls)


@respx.mock
async def test_get_player_stats_simple_payload_shape() -> None:
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, json=_search_payload())
    )
    simple = {
        "athlete": {
            "id": "1966",
            "displayName": "LeBron James",
            "team": {"displayName": "Los Angeles Lakers"},
        },
        "categories": [
            {
                "name": "general",
                "displayName": "General",
                "stats": [
                    {
                        "name": "gamesPlayed",
                        "displayName": "Games Played",
                        "value": 71.0,
                        "displayValue": "71",
                    },
                    {
                        "name": "avgPoints",
                        "displayName": "Points Per Game",
                        "value": 25.7,
                        "displayValue": "25.7",
                    },
                ],
            }
        ],
    }
    respx.get(url__startswith=_STATS).mock(return_value=httpx.Response(200, json=simple))
    result = await stats.get_player_stats("LeBron James", sport="nba")
    assert result["team"] == "Los Angeles Lakers"
    assert result["season"] == str(stats._CURRENT_YEAR)
    assert result["stats"] == {"Games Played": "71", "Points Per Game": "25.7"}


@respx.mock
async def test_get_player_stats_not_found_returns_empty() -> None:
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, json={"count": 0, "items": []})
    )
    assert await stats.get_player_stats("Nobody Known", sport="nba") == {}


@respx.mock
async def test_get_player_stats_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SEARCH).mock(return_value=httpx.Response(500))
    assert await stats.get_player_stats("LeBron James", sport="nba") == {}


@respx.mock
async def test_get_player_stats_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_SEARCH).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await stats.get_player_stats("LeBron James", sport="nba") == {}


@respx.mock
async def test_get_player_stats_invalid_sport_returns_empty() -> None:
    assert await stats.get_player_stats("LeBron James", sport="quidditch") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_player_stats_empty_name_returns_empty() -> None:
    assert await stats.get_player_stats("   ") == {}
    assert respx.calls.call_count == 0


# ── scores: get_scores ────────────────────────────────────────────────


@respx.mock
async def test_get_scores_success_today() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=False))
    )
    results = await scores.get_scores("nba", date="today")
    assert len(results) == 2
    first = results[0]
    assert first["sport"] == "nba"
    assert first["home"] == "Los Angeles Lakers"
    assert first["away"] == "Boston Celtics"
    assert first["home_score"] == "102"
    assert first["away_score"] == "98"
    assert first["status"] == "Final"
    assert results[1]["status"] == "In Progress"


@respx.mock
async def test_get_scores_date_param_normalized() -> None:
    respx.get(url__startswith=_SCORE_NBA, params={"dates": "20260815"}).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=False))
    )
    results = await scores.get_scores("nba", date="2026-08-15")
    assert len(results) == 2
    assert respx.calls.call_count == 1


@respx.mock
async def test_get_scores_all_merges_default_sports() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_espn_scoreboard_payload(with_odds=False))
    )
    respx.get(url__startswith=_SCORE_NFL).mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    respx.get(url__startswith=_SCORE_EPL).mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    results = await scores.get_scores("all")
    assert len(results) == 2
    assert all(record["sport"] == "nba" for record in results)


@respx.mock
async def test_get_scores_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(500))
    assert await scores.get_scores("nba") == []


@respx.mock
async def test_get_scores_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    assert await scores.get_scores("nba") == []


@respx.mock
async def test_get_scores_invalid_sport_returns_empty() -> None:
    assert await scores.get_scores("quidditch") == []
    assert respx.calls.call_count == 0


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def sports_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(sports_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(sports_data, "get_odds")
    assert hasattr(sports_data, "get_event_odds")
    assert hasattr(sports_data, "get_player_stats")
    assert hasattr(sports_data, "get_scores")
    assert hasattr(sports_router_mod, "router")


def test_router_odds_success(sports_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(
        event_query: str = "", sport: str = "all", limit: int = 20
    ) -> list[dict[str, Any]]:
        return [{"sport": "nba", "event": f"match {event_query}", "bookmaker": "DraftKings"}]

    monkeypatch.setattr(odds, "get_odds", fake)
    resp = _client(sports_app).get(
        "/v1/sports/odds", params={"event_query": "celtics", "sport": "nba", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["sport"] == "nba"
    assert body["data"][0]["event"] == "match celtics"


def test_router_event_odds_success(sports_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(event_id: str) -> dict[str, Any]:
        return {"event_id": event_id, "sport": "nba", "bookmakers": []}

    monkeypatch.setattr(odds, "get_event_odds", fake)
    resp = _client(sports_app).get("/v1/sports/odds/nba:eid123")
    assert resp.status_code == 200
    assert resp.json()["data"]["event_id"] == "nba:eid123"


def test_router_stats_success(sports_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(player: str, sport: str = "all") -> dict[str, Any]:
        return {"player": player, "sport": sport, "team": "Los Angeles Lakers", "stats": {}}

    monkeypatch.setattr(stats, "get_player_stats", fake)
    resp = _client(sports_app).get("/v1/sports/stats/LeBron%20James", params={"sport": "nba"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["player"] == "LeBron James"


def test_router_scores_success(sports_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(sport: str, date: str = "today") -> list[dict[str, Any]]:
        return [{"sport": sport, "home": "Lakers", "away": "Celtics", "status": "Final"}]

    monkeypatch.setattr(scores, "get_scores", fake)
    resp = _client(sports_app).get("/v1/sports/scores", params={"sport": "nba", "date": "20260816"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["date"] == "20260816"
    assert body["data"][0]["home"] == "Lakers"


def test_router_502_when_module_absent(
    sports_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sports_router_mod, "_sports_module", lambda name: None)
    assert _client(sports_app).get("/v1/sports/odds").status_code == 502
    assert _client(sports_app).get("/v1/sports/odds/eid123").status_code == 502
    assert _client(sports_app).get("/v1/sports/stats/LeBron%20James").status_code == 502
    assert _client(sports_app).get("/v1/sports/scores").status_code == 502


def test_router_validation_422(sports_app: FastAPI) -> None:
    assert _client(sports_app).get("/v1/sports/odds", params={"limit": 0}).status_code == 422
    assert _client(sports_app).get("/v1/sports/odds", params={"limit": 101}).status_code == 422
