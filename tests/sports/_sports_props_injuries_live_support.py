from __future__ import annotations

from typing import Any

import pytest

import datasets.sports_data.injuries as injuries
import datasets.sports_data.live as live
import datasets.sports_data.props as props


@pytest.fixture(autouse=True)
def _hermetic_sports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the Odds API key so tests are deterministic."""
    monkeypatch.setattr(props, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(injuries, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(live, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)

def _props_events_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "eid123",
            "sport_key": "basketball_nba",
            "commence_time": "2026-08-17T00:00:00Z",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
        }
    ]

def _props_event_payload() -> dict[str, Any]:
    return {
        "id": "eid123",
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
                        "key": "player_points",
                        "outcomes": [
                            {
                                "name": "Over 25.5",
                                "description": "LeBron James Points",
                                "point": 25.5,
                                "price": 1.91,
                            },
                            {
                                "name": "Under 25.5",
                                "description": "LeBron James Points",
                                "point": 25.5,
                                "price": 1.95,
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
                                "price": 1.85,
                            },
                            {
                                "name": "Under 8.5",
                                "description": "LeBron James Rebounds",
                                "point": 8.5,
                                "price": 1.90,
                            },
                        ],
                    },
                ],
            }
        ],
    }

def _props_stats_payload() -> dict[str, Any]:
    return {
        "categories": [
            {
                "name": "averages",
                "displayName": "Regular Season Averages",
                "displayNames": [
                    "Games Played",
                    "Points Per Game",
                    "Rebounds Per Game",
                    "Assists Per Game",
                ],
                "statistics": [
                    {
                        "season": {"year": 2026, "displayName": "2025-26"},
                        "stats": ["60", "25.7", "8.5", "7.4"],
                        "position": "F",
                    }
                ],
            }
        ]
    }

def _search_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "items": [
            {
                "id": "1966",
                "displayName": "LeBron James",
                "type": "player",
                "sport": "basketball",
                "league": "nba",
                "teamRelationships": [
                    {"type": "team", "displayName": "Los Angeles Lakers", "core": {}}
                ],
            }
        ],
    }

def _injuries_payload() -> dict[str, Any]:
    return {
        "athletes": [
            {
                "id": "3945274",
                "fullName": "Anthony Davis",
                "displayName": "Anthony Davis",
                "team": {"id": "13", "displayName": "Los Angeles Lakers", "abbreviation": "LAL"},
                "injury": {
                    "id": "4022508",
                    "status": "Out",
                    "statusDetail": "Out for season - left foot",
                    "type": "Left Foot",
                    "typeDetail": "Foot",
                    "side": "Left",
                    "detail": "Out for season - left foot",
                    "date": "2026-08-10T12:00:00Z",
                    "returnDate": "2026-09-01T00:00:00Z",
                },
                "status": "out",
            },
            {
                "id": "4065806",
                "fullName": "Jayson Tatum",
                "displayName": "Jayson Tatum",
                "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"},
                "injury": {
                    "id": "999",
                    "status": "Questionable",
                    "statusDetail": "Day-to-day - right ankle",
                    "type": "Right Ankle",
                    "typeDetail": "Ankle",
                    "returnDate": None,
                },
                "status": "questionable",
            },
            {
                "id": "4077",
                "fullName": "Kristaps Porzingis",
                "displayName": "Kristaps Porzingis",
                "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"},
                "injury": {
                    "id": "998",
                    "status": "IR",
                    "statusDetail": "Injured Reserve - right calf",
                    "type": "Right Calf",
                    "typeDetail": "Calf",
                    "returnDate": None,
                },
                "status": "ir",
            },
        ]
    }
