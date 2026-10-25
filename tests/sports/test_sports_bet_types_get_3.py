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

import datasets.sports_data.props as props
from pry.engine.retry import RetryConfig

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
from tests.sports._sports_bet_types_support2 import _props_event_payload, _props_events_payload


@respx.mock
async def test_get_player_props_new_market_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NFL}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NFL}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    results = await props.get_player_props("Myles Garrett", sport="nfl", market="sacks")
    assert len(results) == 1
    assert results[0]["market"] == "player_sacks"
    assert results[0]["line"] == 1.5
    assert results[0]["book"] == "DraftKings"
@respx.mock
async def test_get_player_props_multi_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    payload = _props_event_payload()
    payload["bookmakers"][0]["markets"].append(
        {
            "key": "player_pass_yds",
            "outcomes": [
                {
                    "name": "Over 275.5",
                    "description": "Lamar Jackson Passing Yards",
                    "point": 275.5,
                    "price": 1.85,
                }
            ],
        }
    )
    respx.get(url__startswith=f"{_ODDS_NFL}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=payload)
    )
    respx.get(url__startswith=f"{_ODDS_NFL}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    # Two markets requested in one call (comma separated).
    results = await props.get_player_props("Myles Garrett", sport="nfl", market="sacks,pass_yds")
    assert len(results) == 1  # only Myles Garrett matches the player query
    assert results[0]["market"] == "player_sacks"
    # Pipe separated works the same way.
    results2 = await props.get_player_props("Myles Garrett", sport="nfl", market="sacks|pass_yds")
    assert len(results2) == 1
@respx.mock
async def test_get_player_props_raw_odds_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=f"{_ODDS_NFL}/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=_props_event_payload())
    )
    respx.get(url__startswith=f"{_ODDS_NFL}/events").mock(
        return_value=httpx.Response(200, json=_props_events_payload())
    )
    # Unknown player_* keys pass through — new upstream markets work directly.
    results = await props.get_player_props("Myles Garrett", sport="nfl", market="player_sacks")
    assert len(results) == 1
    assert results[0]["market"] == "player_sacks"
@respx.mock
async def test_get_player_props_unknown_market_never_raises() -> None:
    assert await props.get_player_props("LeBron James", sport="nba", market="garbage") == []
@respx.mock
async def test_get_player_props_espn_estimate_new_market() -> None:
    # No key → ESPN season-average estimate path for the new 'sacks' alias.
    respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "items": [
                    {
                        "id": "9912",
                        "displayName": "Myles Garrett",
                        "type": "player",
                        "teamRelationships": [{"type": "team", "displayName": "Cleveland Browns"}],
                    }
                ],
            },
        )
    )
    respx.get(_STATS_NFL).mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": [
                    {
                        "name": "defensive",
                        "displayNames": ["Games Played", "Sacks", "Solo Tackles"],
                        "statistics": [{"season": {"year": 2026}, "stats": ["15", "14.0", "33"]}],
                    }
                ]
            },
        )
    )
    results = await props.get_player_props("Myles Garrett", sport="nfl", market="sacks")
    assert len(results) == 1
    assert results[0]["market"] == "player_sacks"
    assert results[0]["line"] == 14.0
    assert results[0]["source"] == "espn_estimate"
    assert results[0]["book"] == "ESPN Estimate"
