"""Tests for the expanded sports bet types: parlays, alt lines, halves, prop markets.

Covers:

* :mod:`sports_data.parlays` — same-game parlay math (combined odds,
  implied probability, correlation heuristic) and the +EV opportunity scan
  (sharp-book fair-prob anchoring + best-leg selection). The scan's data
  sources (``sports_data.odds.get_event_odds`` / ``sports_data.props
  .get_game_props``) are monkeypatched with async stubs — no HTTP.
* :mod:`sports_data.alt_lines` — The Odds API ``alternate_spreads`` /
  ``alternate_totals`` parsing and the ESPN base-line modeled ladder
  fallback, via respx.
* :mod:`sports_data.halves` — The Odds API period markets (``h1``/``h2``/
  ``q1``..``q4`` + ``_spreads``/``_totals``) and the no-key degradation.
* :mod:`sports_data.props` — ``get_prop_markets`` discovery and the
  expanded ``get_player_props`` market filtering (new aliases, comma/
  pipe-separated multi-market requests, ESPN estimate path).

Every public function is asserted never to raise (HTTP errors and
malformed payloads degrade to ``[]`` / ``{}``).
"""

import httpx
import pytest
import respx

import datasets.sports_data.halves as halves
import datasets.sports_data.props as props
from pry.engine.retry import RetryConfig
from tests.sports._sports_bet_types_support import (
    _event_odds_payload,
    _hermetic_sports,
)
from tests.sports._sports_bet_types_support2 import _periods_payload, _prop_markets_payload
from tests.sports._sports_offshore_european_support import _hermetic  # noqa: F401
from tests.sports._sports_props_injuries_live_support import _hermetic_sports  # noqa: F401

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_NFL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_STATS_NFL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/americanfootball/nfl/athletes/9912/stats"
)
_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@respx.mock
async def test_get_half_quarters_odds_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_periods_payload())
    )
    results = await halves.get_half_quarters("nba:eid123")
    assert len(results) == 4
    by_market = {r["market"]: r for r in results}
    assert by_market["h1"]["period"] == "first_half"
    assert by_market["h1"]["home_odds"] == 1.80
    assert by_market["h1"]["away_odds"] == 2.05
    assert by_market["h1"]["total"] is None
    assert by_market["h1_totals"]["period"] == "first_half"
    assert by_market["h1_totals"]["total"] == 112.5
    assert by_market["h1_totals"]["home_odds"] == 1.91  # Over
    assert by_market["h1_totals"]["away_odds"] == 1.95  # Under
    assert by_market["q1_spreads"]["period"] == "q1"
    assert by_market["q1_spreads"]["line"] == -1.5
    assert by_market["q1_spreads"]["home_odds"] == 1.85
    assert by_market["q2"]["period"] == "q2"
    assert all(r["book"] == "draftkings" for r in results)
    assert all(r["source"] == "the_odds_api" for r in results)
    assert all(r["event"] == "Boston Celtics @ Los Angeles Lakers" for r in results)


@respx.mock
async def test_get_half_quarters_book_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    payload = _event_odds_payload(
        [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h1",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.80},
                            {"name": "Boston Celtics", "price": 2.05},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h1",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.75},
                            {"name": "Boston Celtics", "price": 2.10},
                        ],
                    }
                ],
            },
        ]
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=payload)
    )
    results = await halves.get_half_quarters("nba:eid123", book="fanduel")
    assert len(results) == 1
    assert results[0]["book"] == "fanduel"
    assert results[0]["home_odds"] == 1.75


@respx.mock
async def test_get_half_quarters_no_key_returns_empty() -> None:
    # No Odds API key → [] (ESPN publishes no period odds; no fabrication).
    assert await halves.get_half_quarters("nba:eid123") == []


@respx.mock
async def test_get_half_quarters_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    assert await halves.get_half_quarters("nba:eid123") == []
    assert await halves.get_half_quarters("") == []
    assert await halves.get_half_quarters("bogus:eid123") == []


@respx.mock
async def test_get_prop_markets_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_prop_markets_payload())
    )
    results = await props.get_prop_markets("nba:eid123")
    assert len(results) == 2
    by_market = {r["market"]: r for r in results}
    points = by_market["player_points"]
    assert points["label"] == "Player Points"
    assert points["player_count"] == 2  # LeBron + Tatum
    assert points["book"] == "DraftKings"
    expected = ["DraftKings", "FanDuel"]
    assert points["books"] == expected
    assert points["event"] == "Boston Celtics @ Los Angeles Lakers"
    rebounds = by_market["player_rebounds"]
    assert rebounds["player_count"] == 1
    expected_2 = ["DraftKings"]
    assert rebounds["books"] == expected_2


@respx.mock
async def test_get_prop_markets_no_key_empty() -> None:
    assert await props.get_prop_markets("nba:eid123") == []


@respx.mock
async def test_get_prop_markets_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    assert await props.get_prop_markets("nba:eid123") == []
    assert await props.get_prop_markets("") == []
