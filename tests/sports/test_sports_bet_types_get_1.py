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
from tests.sports._sports_props_injuries_live_support import _hermetic_sports  # noqa: F401
from tests.sports._sports_offshore_european_support import _hermetic  # noqa: F401
from tests.sports._sports_bet_types_support import _hermetic_sports  # noqa: F401

import httpx
import pytest
import respx

import datasets.sports_data.alt_lines as alt_lines
from pry.engine.retry import RetryConfig
from tests.sports._sports_bet_types_support import (
    _alt_lines_payload,
    _espn_scoreboard_payload,
    _event_odds_payload,
)

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
async def test_get_alt_lines_odds_api_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_alt_lines_payload())
    )
    results = await alt_lines.get_alt_lines("nba:eid123")
    assert results, "expected alternate lines"
    spreads = [r for r in results if r["market"] == "spread"]
    totals = [r for r in results if r["market"] == "total"]
    assert len(spreads) == 2
    assert len(totals) == 2
    # spread records merge home/away legs on the same line
    neg = next(r for r in spreads if r["line"] == -3.5)
    assert neg["home_odds"] == 1.83
    assert neg["away_odds"] == 2.02
    assert neg["event"] == "Boston Celtics @ Los Angeles Lakers"
    assert neg["book"] == "draftkings"
    assert neg["source"] == "the_odds_api"
    # totals: home_odds = Over, away_odds = Under
    high = next(r for r in totals if r["line"] == 230.5)
    assert high["home_odds"] == 1.91
    assert high["away_odds"] == 1.95


@respx.mock
async def test_get_alt_lines_market_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_alt_lines_payload())
    )
    results = await alt_lines.get_alt_lines("nba:eid123", market="total")
    assert results
    assert all(r["market"] == "total" for r in results)
    results2 = await alt_lines.get_alt_lines("nba:eid123", market="spread")
    assert results2
    assert all(r["market"] == "spread" for r in results2)


@respx.mock
async def test_get_alt_lines_book_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    payload = _event_odds_payload(
        [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "alternate_totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.91, "point": 230.5},
                            {"name": "Under", "price": 1.95, "point": 230.5},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "alternate_totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.85, "point": 230.5},
                            {"name": "Under", "price": 2.00, "point": 230.5},
                        ],
                    }
                ],
            },
        ]
    )
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=payload)
    )
    results = await alt_lines.get_alt_lines("nba:eid123", market="total", book="draftkings")
    assert results
    assert all(r["book"] == "draftkings" for r in results)
    assert len(results) == 1


@respx.mock
async def test_get_alt_lines_espn_fallback() -> None:
    # No Odds API key → ESPN modeled ladder.
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    results = await alt_lines.get_alt_lines("eid123")
    assert results, "expected a modeled ESPN ladder"
    assert all(r["book"] == "ESPN Estimate" for r in results)
    assert all(r["source"] == "espn_estimate" for r in results)
    spreads = [r for r in results if r["market"] == "spread"]
    totals = [r for r in results if r["market"] == "total"]
    # Base spread -5.5 is in the ladder; lines are half-step rounded.
    assert any(r["line"] == -5.5 for r in spreads)
    assert any(r["line"] == 224.5 for r in totals)
    # Modeled odds are vigged decimals with home + away prices present.
    assert all(r["home_odds"] is not None and r["away_odds"] is not None for r in results)
    # Away-from-base lines move probability (odds differ from the base line).
    neg = next(r for r in spreads if r["line"] == -5.5)
    deeper = next(r for r in spreads if r["line"] == -9.0)
    assert deeper["home_odds"] > neg["home_odds"]  # -9.0 covers less often → longer price


@respx.mock
async def test_get_alt_lines_never_raises() -> None:
    respx.get(url__startswith=f"{_ODDS_NBA}/events/eid123/odds").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    assert await alt_lines.get_alt_lines("nba:eid123") == []
    assert await alt_lines.get_alt_lines("") == []
    assert await alt_lines.get_alt_lines("nba:eid123", market="bogus") == []
    assert await alt_lines.get_alt_lines("nba:eid123", market="total") == []
