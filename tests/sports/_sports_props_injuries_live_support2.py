from __future__ import annotations

from typing import Any


def _report_scoreboard_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "401765432",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "401765432",
                        "status": {
                            "type": {
                                "name": "STATUS_SCHEDULED",
                                "description": "Scheduled",
                                "state": "pre",
                            }
                        },
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
                    }
                ],
            }
        ]
    }


def _live_scoreboard_payload() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "401765433",
                "name": "Warriors at Suns",
                "competitions": [
                    {
                        "id": "401765433",
                        "status": {
                            "type": {
                                "name": "STATUS_IN_PROGRESS",
                                "description": "In Progress",
                                "state": "in",
                                "shortDetail": "Q2 4:11",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Phoenix Suns"},
                                "score": "45",
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Golden State Warriors"},
                                "score": "50",
                            },
                        ],
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "details": "GSW -5.5",
                                "overUnder": 224.5,
                                "spread": -5.5,
                            }
                        ],
                    }
                ],
            },
            {
                "id": "401765434",
                "name": "Celtics at Lakers",
                "competitions": [
                    {
                        "id": "401765434",
                        "status": {
                            "type": {
                                "name": "STATUS_FINAL",
                                "description": "Final",
                                "state": "post",
                                "shortDetail": "Final",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Los Angeles Lakers"},
                                "score": "102",
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Boston Celtics"},
                                "score": "98",
                            },
                        ],
                        "odds": [],
                    }
                ],
            },
        ]
    }


def _odds_api_live_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "live1",
            "sport_key": "basketball_nba",
            "commence_time": "2026-08-16T00:00:00Z",
            "home_team": "Phoenix Suns",
            "away_team": "Golden State Warriors",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2026-08-16T18:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Phoenix Suns", "price": 2.10},
                                {"name": "Golden State Warriors", "price": 1.85},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


def _team_injuries_html() -> str:
    return (
        "<html><body><table>"
        "<tr><td>LeBron James</td><td>Out</td><td>Left foot</td></tr>"
        "<tr><td>Anthony Davis</td><td>Questionable</td><td>Back</td></tr>"
        "<tr><td>Austin Reaves</td><td>Healthy</td><td></td></tr>"
        "</table></body></html>"
    )
