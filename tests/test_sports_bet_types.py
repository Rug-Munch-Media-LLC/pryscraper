# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
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

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

import sports_data.alt_lines as alt_lines
import sports_data.halves as halves
import sports_data.parlays as parlays
import sports_data.props as props
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


@pytest.fixture(autouse=True)
def _hermetic_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the Odds API key so tests are deterministic."""
    monkeypatch.setattr(alt_lines, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(halves, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(props, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)


# ── Shared fixtures ────────────────────────────────────────────────────


def _event_odds_payload(
    bookmakers: list[dict[str, Any]],
) -> dict[str, Any]:
    """An Odds API per-event odds payload (home=LA Lakers, away=Celtics)."""
    return {
        "id": "eid123",
        "sport_key": "basketball_nba",
        "commence_time": "2026-08-17T00:00:00Z",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": bookmakers,
    }


def _comparison_payload() -> dict[str, Any]:
    """``sports_data.odds.get_event_odds`` comparison dict (two books)."""
    return {
        "event_id": "eid123",
        "sport": "basketball_nba",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "commence_time": "2026-08-17T00:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "book": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 2.00},
                            {"name": "Boston Celtics", "price": 2.00},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 2.00, "point": 224.5},
                            {"name": "Under", "price": 2.00, "point": 224.5},
                        ],
                    },
                ],
            },
            {
                "key": "draftkings",
                "title": "DraftKings",
                "book": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 2.15},
                            {"name": "Boston Celtics", "price": 1.80},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.90, "point": 224.5},
                            {"name": "Under", "price": 2.10, "point": 224.5},
                        ],
                    },
                ],
            },
        ],
        "source": "the_odds_api",
    }


def _game_props_records() -> list[dict[str, Any]]:
    """``sports_data.props.get_game_props`` records for DraftKings."""
    return [
        {
            "player": "LeBron James",
            "sport": "nba",
            "market": "player_points",
            "line": 25.5,
            "over_odds": 2.10,
            "under_odds": 1.90,
            "book": "DraftKings",
            "source": "the_odds_api",
        }
    ]


def _espn_scoreboard_payload() -> dict[str, Any]:
    """ESPN scoreboard event with a base spread + total for the Lakers/Celtics."""
    return {
        "events": [
            {
                "id": "eid123",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "eid123",
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
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "details": "LAL -5.5",
                                "overUnder": 224.5,
                                "spread": -5.5,
                            }
                        ],
                    }
                ],
            }
        ]
    }


# ══ parlays: build_same_game_parlay ═══════════════════════════════════


async def test_build_same_game_parlay_math() -> None:
    result = await parlays.build_same_game_parlay(
        "nba:eid123",
        [
            {"market": "spread", "side": "home", "team": "Lakers", "line": -5.5, "odds": 1.91},
            {"market": "total", "side": "over", "line": 224.5, "odds": 1.95},
            {"market": "player_points", "player": "LeBron James", "line": 25.5, "odds": 1.91},
        ],
        book="draftkings",
    )
    assert result["combined_odds"] == pytest.approx(1.91 * 1.95 * 1.91)
    assert result["implied_prob"] == pytest.approx((1 / 1.91) * (1 / 1.95) * (1 / 1.91))
    assert result["parlay"]["leg_count"] == 3
    assert result["parlay"]["book"] == "draftkings"
    assert result["parlay"]["event_id"] == "nba:eid123"
    assert result["source"] == "parlay_math"
    # legs carry per-leg implied probability
    assert result["legs"][0]["implied_prob"] == pytest.approx(1 / 1.91)
    assert result["legs"][0]["line"] == -5.5


async def test_build_same_game_parlay_correlation_shared_team() -> None:
    # Spread + player prop on the same team → correlated.
    result = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "spread", "side": "home", "team": "Lakers", "odds": 1.91},
            {"market": "player_points", "player": "LeBron James", "team": "Lakers", "odds": 1.91},
        ],
    )
    assert result["correlation_flag"] is True


async def test_build_same_game_parlay_correlation_team_markets() -> None:
    # No entity info, but spread + total are two team-market classes → correlated.
    result = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "spread", "side": "home", "line": -5.5, "odds": 1.91},
            {"market": "total", "side": "over", "line": 224.5, "odds": 1.95},
        ],
    )
    assert result["correlation_flag"] is True


async def test_build_same_game_parlay_correlation_independent_players() -> None:
    # Two player props on different players, no team info → not correlated.
    result = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "player_points", "player": "LeBron James", "odds": 1.91},
            {"market": "player_points", "player": "Jayson Tatum", "odds": 1.85},
        ],
    )
    assert result["correlation_flag"] is False
    # side defaults to the player name for player props
    assert result["legs"][0]["side"] == "LeBron James"


async def test_build_same_game_parlay_same_book_mixed() -> None:
    result = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "h2h", "side": "home", "odds": 2.0, "book": "pinnacle"},
            {"market": "total", "side": "over", "odds": 2.0},
        ],
    )
    # one explicit book + one bookless leg → the explicit book wins
    assert result["parlay"]["book"] == "pinnacle"
    result2 = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "h2h", "side": "home", "odds": 2.0, "book": "pinnacle"},
            {"market": "total", "side": "over", "odds": 2.0, "book": "draftkings"},
        ],
    )
    assert result2["parlay"]["book"] == "mixed"


async def test_build_same_game_parlay_never_raises() -> None:
    # Fewer than two valid legs → {} (never raises).
    assert await parlays.build_same_game_parlay("eid123", []) == {}
    assert await parlays.build_same_game_parlay("eid123", [{"market": "h2h", "side": "home"}]) == {}
    # Legs with invalid odds are dropped; a bogus-but-priced market is a
    # legitimate (caller-defined) selection, so 2 valid legs still build.
    result = await parlays.build_same_game_parlay(
        "eid123",
        [
            {"market": "h2h", "side": "home", "odds": 0.5},
            {"market": "custom_market", "side": "x", "odds": 2.0},
            {"market": "total", "side": "over", "odds": 2.0},
        ],
    )
    assert result["parlay"]["leg_count"] == 2
    assert result["combined_odds"] == pytest.approx(4.0)
    # Garbage input (not even a dict) never raises.
    assert await parlays.build_same_game_parlay("eid123", "garbage") == {}


# ══ parlays: find_parlay_opportunities ════════════════════════════════


async def test_find_parlay_opportunities_plus_ev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_event_odds(
        event_id: str, market: str = "h2h", book: str | None = None
    ) -> dict[str, Any]:
        return _comparison_payload()

    async def _fake_game_props(event_id: str) -> list[dict[str, Any]]:
        return _game_props_records()

    monkeypatch.setattr(parlays, "_get_event_odds", _fake_event_odds)
    monkeypatch.setattr(parlays, "_get_game_props", _fake_game_props)

    results = await parlays.find_parlay_opportunities("nba:eid123", min_ev_pct=2.0)
    assert results, "expected at least one +EV combo"
    top = results[0]
    # Best legs: Lakers ML 2.15 (DraftKings) + Under 224.5 2.10 (DraftKings);
    # fair probs 0.5/0.5 anchored on Pinnacle (margin 0) → 0.25 * 4.515 → +12.9%.
    assert top["combined_odds"] == pytest.approx(2.15 * 2.10)
    assert top["fair_prob"] == pytest.approx(0.25)
    assert top["ev_pct"] == pytest.approx(12.875, abs=0.01)
    assert top["book"] == "draftkings"
    assert top["correlation_flag"] is True
    assert len(top["legs"]) == 2
    assert top["legs"][0]["market"] == "h2h"
    assert top["legs"][1]["market"] == "total"
    # best-EV first
    evs = [float(item["ev_pct"]) for item in results]
    assert evs == sorted(evs, reverse=True)
    # a player-prop combo is included (prop over 2.10 + total under 2.10 → +4.7%)
    assert any(
        {leg["market"] for leg in item["legs"]} == {"player_points", "total"} for item in results
    )


async def test_find_parlay_opportunities_mixed_book_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_event_odds(
        event_id: str, market: str = "h2h", book: str | None = None
    ) -> dict[str, Any]:
        # Add a spread market only at Pinnacle so the best legs come from
        # different books for one combo.
        comparison = _comparison_payload()
        comparison["bookmakers"][0]["markets"].append(
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "Los Angeles Lakers", "price": 1.91, "point": -5.5},
                    {"name": "Boston Celtics", "price": 1.95, "point": 5.5},
                ],
            }
        )
        return comparison

    async def _fake_game_props(event_id: str) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(parlays, "_get_event_odds", _fake_event_odds)
    monkeypatch.setattr(parlays, "_get_game_props", _fake_game_props)

    results = await parlays.find_parlay_opportunities("eid123")
    assert any(item["book"] == "mixed" for item in results)
    assert any(item["book"] == "draftkings" for item in results)


async def test_find_parlay_opportunities_threshold_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_event_odds(
        event_id: str, market: str = "h2h", book: str | None = None
    ) -> dict[str, Any]:
        return _comparison_payload()

    async def _fake_game_props(event_id: str) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(parlays, "_get_event_odds", _fake_event_odds)
    monkeypatch.setattr(parlays, "_get_game_props", _fake_game_props)

    # Threshold 20% → the 15.5% combo is filtered out.
    results = await parlays.find_parlay_opportunities("eid123", min_ev_pct=20.0)
    assert results == []


async def test_find_parlay_opportunities_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom_event_odds(
        event_id: str, market: str = "h2h", book: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("upstream exploded")

    async def _boom_game_props(event_id: str) -> list[dict[str, Any]]:
        raise RuntimeError("props exploded")

    monkeypatch.setattr(parlays, "_get_event_odds", _boom_event_odds)
    monkeypatch.setattr(parlays, "_get_game_props", _boom_game_props)
    assert await parlays.find_parlay_opportunities("eid123") == []

    # Missing guards → [].
    monkeypatch.setattr(parlays, "_get_event_odds", None)
    assert await parlays.find_parlay_opportunities("eid123") == []

    # Empty comparison → [].
    async def _empty_event_odds(
        event_id: str, market: str = "h2h", book: str | None = None
    ) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(parlays, "_get_event_odds", _empty_event_odds)
    assert await parlays.find_parlay_opportunities("eid123") == []


# ══ alt_lines: The Odds API path ══════════════════════════════════════


def _alt_lines_payload() -> dict[str, Any]:
    return _event_odds_payload(
        [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "alternate_spreads",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.83, "point": -3.5},
                            {"name": "Boston Celtics", "price": 2.02, "point": 3.5},
                            {"name": "Los Angeles Lakers", "price": 2.20, "point": -7.5},
                            {"name": "Boston Celtics", "price": 1.70, "point": 7.5},
                        ],
                    },
                    {
                        "key": "alternate_totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.91, "point": 230.5},
                            {"name": "Under", "price": 1.95, "point": 230.5},
                            {"name": "Over", "price": 1.75, "point": 218.5},
                            {"name": "Under", "price": 2.15, "point": 218.5},
                        ],
                    },
                ],
            }
        ]
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


# ══ halves: period markets ═════════════════════════════════════════════


def _periods_payload() -> dict[str, Any]:
    return _event_odds_payload(
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
                    },
                    {
                        "key": "h1_totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.91, "point": 112.5},
                            {"name": "Under", "price": 1.95, "point": 112.5},
                        ],
                    },
                    {
                        "key": "q1_spreads",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.85, "point": -1.5},
                            {"name": "Boston Celtics", "price": 2.00, "point": 1.5},
                        ],
                    },
                    {
                        "key": "q2",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.95},
                            {"name": "Boston Celtics", "price": 1.90},
                        ],
                    },
                ],
            }
        ]
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


# ══ props: get_prop_markets ═══════════════════════════════════════════


def _prop_markets_payload() -> dict[str, Any]:
    return _event_odds_payload(
        [
            {
                "key": "draftkings",
                "title": "DraftKings",
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
                                "name": "Over 22.5",
                                "description": "Jayson Tatum Points",
                                "point": 22.5,
                                "price": 1.85,
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
                                "price": 1.90,
                            }
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {
                                "name": "Over 25.5",
                                "description": "LeBron James Points",
                                "point": 25.5,
                                "price": 1.95,
                            }
                        ],
                    }
                ],
            },
        ]
    )


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
    assert points["books"] == ["DraftKings", "FanDuel"]
    assert points["event"] == "Boston Celtics @ Los Angeles Lakers"
    rebounds = by_market["player_rebounds"]
    assert rebounds["player_count"] == 1
    assert rebounds["books"] == ["DraftKings"]


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


# ══ props: expanded get_player_props market filtering ═════════════════


def _props_events_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "eid123",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2026-08-17T00:00:00Z",
            "home_team": "Cleveland Browns",
            "away_team": "Baltimore Ravens",
        }
    ]


def _props_event_payload() -> dict[str, Any]:
    return {
        "id": "eid123",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2026-08-17T00:00:00Z",
        "home_team": "Cleveland Browns",
        "away_team": "Baltimore Ravens",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "player_sacks",
                        "outcomes": [
                            {
                                "name": "Over 1.5",
                                "description": "Myles Garrett Sacks",
                                "point": 1.5,
                                "price": 1.90,
                            },
                            {
                                "name": "Under 1.5",
                                "description": "Myles Garrett Sacks",
                                "point": 1.5,
                                "price": 1.95,
                            },
                        ],
                    }
                ],
            }
        ],
    }


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
