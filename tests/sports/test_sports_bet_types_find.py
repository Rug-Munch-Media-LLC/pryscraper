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

from typing import Any

import httpx
import pytest

import datasets.sports_data.parlays as parlays
from pry.engine.retry import RetryConfig
from tests.sports._sports_bet_types_support import _comparison_payload, _game_props_records

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
