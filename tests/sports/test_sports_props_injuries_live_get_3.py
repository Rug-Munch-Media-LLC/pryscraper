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

import datasets.sports_data.injuries as injuries
import datasets.sports_data.live as live
from pry.engine.retry import RetryConfig
from tests.sports._sports_props_injuries_live_support2 import (
    _live_scoreboard_payload,
    _odds_api_live_payload,
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
async def test_get_injury_report_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SCORE_NBA).mock(return_value=httpx.Response(500))
    assert await injuries.get_injury_report("401765432") == []


@respx.mock
async def test_get_injury_report_empty_id_returns_empty() -> None:
    assert await injuries.get_injury_report("") == []
    assert respx.calls.call_count == 0


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
