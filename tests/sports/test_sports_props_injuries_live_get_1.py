"""Tests for sports_data.props / injuries / live (player props, injuries, live data).

Covers The Odds API player-props fetching (events scan + per-event odds) and
the ESPN season-average estimate fallback, ESPN injury feeds + the
best-effort team-site scrape fallback, ESPN live scoreboards (in-progress
filter, clock parsing, 403-defensive degradation) and the The Odds API
in-play odds merge, plus the never-raise contract (HTTP errors and
malformed payloads degrade to empty output).

All HTTP is mocked with respx — no live network.
"""
from tests.sports._sports_props_injuries_live_support import _hermetic_sports  # noqa: F401
from tests.sports._sports_offshore_european_support import _hermetic  # noqa: F401
from tests.sports._sports_bet_types_support import _hermetic_sports  # noqa: F401

import httpx
import pytest
import respx

import datasets.sports_data.props as props
from pry.engine.retry import RetryConfig
from tests.sports._sports_props_injuries_live_support import (
    _props_event_payload,
    _props_events_payload,
    _props_stats_payload,
    _search_payload,
)

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_INJ_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
_TEAM_INJ_NBA = "https://www.espn.com/nba/team/injuries/_/name/lal"
_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_STATS = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/1966/stats"
_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


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
    expected = {"player_points", "player_rebounds"}
    assert {record["market"] for record in results} == expected


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
