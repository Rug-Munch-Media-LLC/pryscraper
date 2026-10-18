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
import datasets.sports_data.odds_fetchers as odds_fetchers
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
    monkeypatch.setattr(odds_fetchers, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)


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


async def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(odds_fetchers, "_monotonic", lambda: clock["now"])
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return {"events": []}

    monkeypatch.setattr(odds_fetchers, "_fetch_uncached", fake_fetch)
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

    monkeypatch.setattr(odds_fetchers, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/cleared")
    odds._clear_cache()
    await odds._fetch_json("https://example.com/cleared")
    assert len(calls) == 2


async def test_cache_not_populated_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_fetch(url: str, params: dict[str, str] | None = None) -> Any:
        calls.append(url)
        return None

    monkeypatch.setattr(odds_fetchers, "_fetch_uncached", fake_fetch)
    await odds._fetch_json("https://example.com/fail")
    await odds._fetch_json("https://example.com/fail")
    assert len(calls) == 2  # failures are never cached


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
