from __future__ import annotations

from typing import Any

from tests.sports._sports_bet_types_support import _event_odds_payload


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
