from __future__ import annotations

from typing import Any

import pytest

import datasets.sports_data.alt_lines as alt_lines
import datasets.sports_data.halves as halves
import datasets.sports_data.props as props


@pytest.fixture(autouse=True)
def _hermetic_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the Odds API key so tests are deterministic."""
    monkeypatch.setattr(alt_lines, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(halves, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(props, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)

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
