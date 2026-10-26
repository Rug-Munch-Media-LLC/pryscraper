"""Tests for sports_data.props / injuries / live (player props, injuries, live data).

Covers The Odds API player-props fetching (events scan + per-event odds) and
the ESPN season-average estimate fallback, ESPN injury feeds + the
best-effort team-site scrape fallback, ESPN live scoreboards (in-progress
filter, clock parsing, 403-defensive degradation) and the The Odds API
in-play odds merge, plus the never-raise contract (HTTP errors and
malformed payloads degrade to empty output).

All HTTP is mocked with respx — no live network.
"""
import httpx
import pytest
import respx

import datasets.sports_data.injuries as injuries
import datasets.sports_data.props as props
from pry.engine.retry import RetryConfig
from tests.sports._sports_bet_types_support import _hermetic_sports
from tests.sports._sports_offshore_european_support import _hermetic  # noqa: F401
from tests.sports._sports_props_injuries_live_support import (
    _hermetic_sports,  # noqa: F401
    _injuries_payload,
    _props_event_payload,
)
from tests.sports._sports_props_injuries_live_support2 import (
    _report_scoreboard_payload,
    _team_injuries_html,
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
    expected = {
        "Los Angeles Lakers",
        "Boston Celtics",
    }
    assert {record["team"] for record in results} == expected


@respx.mock
async def test_get_injury_report_game_not_found_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    assert await injuries.get_injury_report("nba:999999") == []
