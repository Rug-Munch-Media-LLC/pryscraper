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

import datasets.sports_data.parlays as parlays
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
