# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for sports_data.props / injuries / live (player props, injuries, live data).

Covers The Odds API player-props fetching (events scan + per-event odds) and
the ESPN season-average estimate fallback, ESPN injury feeds + the
best-effort team-site scrape fallback, ESPN live scoreboards (in-progress
filter, clock parsing, 403-defensive degradation) and the The Odds API
in-play odds merge, plus the never-raise contract (HTTP errors and
malformed payloads degrade to empty output).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

import datasets.sports_data.injuries as injuries
import datasets.sports_data.live as live
import datasets.sports_data.props as props
from pry.engine.retry import RetryConfig

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_INJ_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
_TEAM_INJ_NBA = "https://www.espn.com/nba/team/injuries/_/name/lal"
_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_STATS = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/1966/stats"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the Odds API key so tests are deterministic."""
    monkeypatch.setattr(props, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(injuries, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(live, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _props_events_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "eid123",
            "sport_key": "basketball_nba",
            "commence_time": "2026-08-17T00:00:00Z",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
        }
    ]


def _props_event_payload() -> dict[str, Any]:
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
                        "key": "player_points",
                        "outcomes": [
                            {
                                "name": "Over 25.5",
                                "description": "LeBron James Points",
                                "point": 25.5,
                                "price": 1.91,
                            },
                            {
                                "name": "Under 25.5",
                                "description": "LeBron James Points",
                                "point": 25.5,
                                "price": 1.95,
                            },
                        ],
                    },
                    {
                        "key": "player_rebounds",
                        "outcomes": [
                            {
                                "name": "Over 8.5",
                                "description": "LeBron James Rebounds",
                                "point": 8.5,
                                "price": 1.85,
                            },
                            {
                                "name": "Under 8.5",
                                "description": "LeBron James Rebounds",
                                "point": 8.5,
                                "price": 1.90,
                            },
                        ],
                    },
                ],
            }
        ],
    }


def _props_stats_payload() -> dict[str, Any]:
    return {
        "categories": [
            {
                "name": "averages",
                "displayName": "Regular Season Averages",
                "displayNames": [
                    "Games Played",
                    "Points Per Game",
                    "Rebounds Per Game",
                    "Assists Per Game",
                ],
                "statistics": [
                    {
                        "season": {"year": 2026, "displayName": "2025-26"},
                        "stats": ["60", "25.7", "8.5", "7.4"],
                        "position": "F",
                    }
                ],
            }
        ]
    }


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


def _injuries_payload() -> dict[str, Any]:
    return {
        "athletes": [
            {
                "id": "3945274",
                "fullName": "Anthony Davis",
                "displayName": "Anthony Davis",
                "team": {"id": "13", "displayName": "Los Angeles Lakers", "abbreviation": "LAL"},
                "injury": {
                    "id": "4022508",
                    "status": "Out",
                    "statusDetail": "Out for season - left foot",
                    "type": "Left Foot",
                    "typeDetail": "Foot",
                    "side": "Left",
                    "detail": "Out for season - left foot",
                    "date": "2026-08-10T12:00:00Z",
                    "returnDate": "2026-09-01T00:00:00Z",
                },
                "status": "out",
            },
            {
                "id": "4065806",
                "fullName": "Jayson Tatum",
                "displayName": "Jayson Tatum",
                "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"},
                "injury": {
                    "id": "999",
                    "status": "Questionable",
                    "statusDetail": "Day-to-day - right ankle",
                    "type": "Right Ankle",
                    "typeDetail": "Ankle",
                    "returnDate": None,
                },
                "status": "questionable",
            },
            {
                "id": "4077",
                "fullName": "Kristaps Porzingis",
                "displayName": "Kristaps Porzingis",
                "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"},
                "injury": {
                    "id": "998",
                    "status": "IR",
                    "statusDetail": "Injured Reserve - right calf",
                    "type": "Right Calf",
                    "typeDetail": "Calf",
                    "returnDate": None,
                },
                "status": "ir",
            },
        ]
    }


def _report_scoreboard_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "401765432",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "401765432",
                        "status": {
                            "type": {
                                "name": "STATUS_SCHEDULED",
                                "description": "Scheduled",
                                "state": "pre",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Los Angeles Lakers"},
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Boston Celtics"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def _live_scoreboard_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "401765433",
                "name": "Warriors at Suns",
                "competitions": [
                    {
                        "id": "401765433",
                        "status": {
                            "type": {
                                "name": "STATUS_IN_PROGRESS",
                                "description": "In Progress",
                                "state": "in",
                                "shortDetail": "Q2 4:11",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Phoenix Suns"},
                                "score": "45",
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Golden State Warriors"},
                                "score": "50",
                            },
                        ],
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "details": "GSW -5.5",
                                "overUnder": 224.5,
                                "spread": -5.5,
                            }
                        ],
                    }
                ],
            },
            {
                "id": "401765434",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "401765434",
                        "status": {
                            "type": {
                                "name": "STATUS_FINAL",
                                "description": "Final",
                                "state": "post",
                                "shortDetail": "Final",
                            }
                        },
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
                        "odds": [],
                    }
                ],
            },
        ]
    }


def _odds_api_live_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "live1",
            "sport_key": "basketball_nba",
            "commence_time": "2026-08-16T00:00:00Z",
            "home_team": "Phoenix Suns",
            "away_team": "Golden State Warriors",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2026-08-16T18:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Phoenix Suns", "price": 2.10},
                                {"name": "Golden State Warriors", "price": 1.85},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


def _team_injuries_html() -> str:
    return (
        "<html><body><table>"
        "<tr><td>LeBron James</td><td>Out</td><td>Left foot</td></tr>"
        "<tr><td>Anthony Davis</td><td>Questionable</td><td>Back</td></tr>"
        "<tr><td>Austin Reaves</td><td>Healthy</td><td></td></tr>"
        "</table></body></html>"
    )


# ── props: get_player_props — The Odds API path ───────────────────────


@respx.mock
async def test_get_player_props_odds_api_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    # Register the more specific odds URL first; respx matches in order.
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    results = await props.get_player_props("LeBron James", sport="nba", market="player_points")
    assert len(results) == 1
    record = results[0]
    assert record["player"] == "LeBron James"
    assert record["sport"] == "nba"
    assert record["market"] == "player_points"
    assert record["line"] == 25.5
    assert record["over_odds"] == 1.91
    assert record["under_odds"] == 1.95
    assert record["book"] == "DraftKings"
    assert record["source"] == "the_odds_api"


@respx.mock
async def test_get_player_props_odds_api_all_markets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    results = await props.get_player_props("LeBron James", sport="nba")
    assert {record["market"] for record in results} == {"player_points", "player_rebounds"}


@respx.mock
async def test_get_player_props_odds_api_no_player_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    assert await props.get_player_props("Jayson Tatum", sport="nba") == []


@respx.mock
async def test_get_player_props_limit_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    results = await props.get_player_props("LeBron James", sport="nba", limit=1)
    assert len(results) == 1


# ── props: get_player_props — ESPN estimate fallback ──────────────────


@respx.mock
async def test_get_player_props_espn_estimate_fallback() -> None:
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, json=_search_payload())
    )
    respx.get(url__startswith=_STATS).mock(
        return_value=httpx.Response(200, json=_props_stats_payload())
    )
    results = await props.get_player_props("LeBron James", sport="nba")
    assert len(results) == 3
    by_market = {record["market"]: record for record in results}
    points = by_market["player_points"]
    assert points["player"] == "LeBron James"
    assert points["sport"] == "nba"
    assert points["line"] == 25.5  # 25.7 -> nearest 0.5
    assert points["over_odds"] is None
    assert points["under_odds"] is None
    assert points["book"] == "ESPN Estimate"
    assert points["source"] == "espn_estimate"
    assert by_market["player_rebounds"]["line"] == 8.5
    assert by_market["player_assists"]["line"] == 7.5


@respx.mock
async def test_get_player_props_espn_estimate_unknown_player() -> None:
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, json={"count": 0, "items": []})
    )
    assert await props.get_player_props("Nobody Known", sport="nba") == []


# ── props: never-raise ────────────────────────────────────────────────


@respx.mock
async def test_get_player_props_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(return_value=httpx.Response(500))
    assert await props.get_player_props("LeBron James", sport="nba") == []


@respx.mock
async def test_get_player_props_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events").mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    assert await props.get_player_props("LeBron James", sport="nba") == []


@respx.mock
async def test_get_player_props_invalid_sport_returns_empty() -> None:
    assert await props.get_player_props("LeBron James", sport="quidditch") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_player_props_empty_name_returns_empty() -> None:
    assert await props.get_player_props("   ") == []
    assert respx.calls.call_count == 0


# ── props: get_game_props ─────────────────────────────────────────────


@respx.mock
async def test_get_game_props_odds_api_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    results = await props.get_game_props("nba:eid123")
    assert len(results) == 2  # player_points + player_rebounds
    by_market = {record["market"]: record for record in results}
    points = by_market["player_points"]
    assert points["player"] == "LeBron James"
    assert points["sport"] == "nba"
    assert points["line"] == 25.5
    assert points["over_odds"] == 1.91
    assert points["under_odds"] == 1.95
    assert points["book"] == "DraftKings"
    assert points["source"] == "the_odds_api"


@respx.mock
async def test_get_game_props_no_key_returns_empty() -> None:
    assert await props.get_game_props("eid123") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_game_props_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(500)
    )
    assert await props.get_game_props("nba:eid123") == []


@respx.mock
async def test_get_game_props_empty_id_returns_empty() -> None:
    assert await props.get_game_props("") == []
    assert respx.calls.call_count == 0


# ── injuries: get_injuries ────────────────────────────────────────────


@respx.mock
async def test_get_injuries_success() -> None:
    respx.get(url__startswith=_INJ_NBA).mock(
        return_value=httpx.Response(200, json=_injuries_payload())
    )
    results = await injuries.get_injuries("nba")
    assert len(results) == 3
    first = results[0]
    assert first["player"] == "Anthony Davis"
    assert first["team"] == "Los Angeles Lakers"
    assert first["status"] == "out"
    assert first["injury"] == "Foot"
    assert first["return_estimate"] == "2026-09-01T00:00:00Z"
    assert first["sport"] == "nba"
    assert first["source"] == "espn"
    assert results[1]["status"] == "questionable"
    assert results[2]["status"] == "IR"


@respx.mock
async def test_get_injuries_team_filter() -> None:
    respx.get(url__startswith=_INJ_NBA).mock(
        return_value=httpx.Response(200, json=_injuries_payload())
    )
    results = await injuries.get_injuries("nba", team="celtics")
    assert len(results) == 2
    assert all(record["team"] == "Boston Celtics" for record in results)


@respx.mock
async def test_get_injuries_team_filter_triggers_scrape_fallback() -> None:
    # Empty JSON feed + a specific team -> best-effort team-site scrape.
    respx.get(url__startswith=_INJ_NBA).mock(
        return_value=httpx.Response(200, json={"athletes": []})
    )
    respx.get(url__startswith=_TEAM_INJ_NBA).mock(
        return_value=httpx.Response(200, text=_team_injuries_html())
    )
    results = await injuries.get_injuries("nba", team="LAL")
    assert len(results) == 2
    assert results[0]["player"] == "LeBron James"
    assert results[0]["status"] == "out"
    assert results[0]["injury"] == "Left foot"
    assert results[0]["source"] == "team_site"
    assert results[1]["status"] == "questionable"


@respx.mock
async def test_get_injuries_http_error_returns_empty() -> None:
    respx.get(url__startswith=_INJ_NBA).mock(return_value=httpx.Response(500))
    assert await injuries.get_injuries("nba") == []


@respx.mock
async def test_get_injuries_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_INJ_NBA).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await injuries.get_injuries("nba") == []


@respx.mock
async def test_get_injuries_invalid_sport_returns_empty() -> None:
    assert await injuries.get_injuries("quidditch") == []
    assert respx.calls.call_count == 0


# ── injuries: get_injury_report ───────────────────────────────────────


@respx.mock
async def test_get_injury_report_success() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_report_scoreboard_payload())
    )
    respx.get(url__startswith=_INJ_NBA).mock(
        return_value=httpx.Response(200, json=_injuries_payload())
    )
    results = await injuries.get_injury_report("nba:401765432")
    assert len(results) == 3  # both teams' injuries
    assert {record["team"] for record in results} == {
        "Los Angeles Lakers",
        "Boston Celtics",
    }


@respx.mock
async def test_get_injury_report_game_not_found_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    assert await injuries.get_injury_report("nba:999999") == []


@respx.mock
async def test_get_injury_report_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(500))
    assert await injuries.get_injury_report("401765432") == []


@respx.mock
async def test_get_injury_report_empty_id_returns_empty() -> None:
    assert await injuries.get_injury_report("") == []
    assert respx.calls.call_count == 0


# ── live: get_live_scores ─────────────────────────────────────────────


@respx.mock
async def test_get_live_scores_success() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_live_scoreboard_payload())
    )
    results = await live.get_live_scores("nba")
    assert len(results) == 1  # only the in-progress game
    record = results[0]
    assert record["sport"] == "nba"
    assert record["event"] == "Golden State Warriors @ Phoenix Suns"
    assert record["home"] == "Phoenix Suns"
    assert record["away"] == "Golden State Warriors"
    assert record["home_score"] == "45"
    assert record["away_score"] == "50"
    assert record["status"] == "In Progress"
    assert record["clock"] == "Q2 4:11"


@respx.mock
async def test_get_live_scores_403_defensive_returns_empty() -> None:
    # Some egress IPs get 403 from ESPN; must degrade to [] and never raise.
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(403))
    assert await live.get_live_scores("nba") == []


@respx.mock
async def test_get_live_scores_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(500))
    assert await live.get_live_scores("nba") == []


@respx.mock
async def test_get_live_scores_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    assert await live.get_live_scores("nba") == []


@respx.mock
async def test_get_live_scores_invalid_sport_returns_empty() -> None:
    assert await live.get_live_scores("quidditch") == []
    assert respx.calls.call_count == 0


# ── live: get_live_odds ───────────────────────────────────────────────


@respx.mock
async def test_get_live_odds_espn_success() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_live_scoreboard_payload())
    )
    results = await live.get_live_odds("nba")
    assert len(results) == 2  # spread + total for the in-progress game
    spread = next(record for record in results if record["market"] == "spread")
    assert spread["event"] == "Golden State Warriors @ Phoenix Suns"
    assert spread["book"] == "DraftKings"
    assert spread["odds"] == -5.5
    assert spread["live_score"] == "50 - 45"
    assert spread["clock"] == "Q2 4:11"
    total = next(record for record in results if record["market"] == "total")
    assert total["odds"] == 224.5


@respx.mock
async def test_get_live_odds_odds_api_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_live_scoreboard_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/odds").mock(
        return_value=httpx.Response(200, json=_odds_api_live_payload())
    )
    results = await live.get_live_odds("nba")
    # 2 ESPN records + 2 Odds API h2h outcomes for the in-play event.
    assert len(results) == 4
    odds_api = [record for record in results if record["last_update"] == "2026-08-16T18:00:00Z"]
    assert len(odds_api) == 2
    assert odds_api[0]["market"] == "h2h"
    assert odds_api[0]["book"] == "DraftKings"
    assert odds_api[0]["live_score"] is None
    assert odds_api[0]["clock"] is None


@respx.mock
async def test_get_live_odds_403_defensive_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(403))
    assert await live.get_live_odds("nba") == []


@respx.mock
async def test_get_live_odds_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(500))
    assert await live.get_live_odds("nba") == []


@respx.mock
async def test_get_live_odds_limit_truncates() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json=_live_scoreboard_payload())
    )
    results = await live.get_live_odds("nba", limit=1)
    assert len(results) == 1


@respx.mock
async def test_get_live_odds_invalid_sport_returns_empty() -> None:
    assert await live.get_live_odds("quidditch") == []
    assert respx.calls.call_count == 0
