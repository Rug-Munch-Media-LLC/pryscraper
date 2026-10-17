# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the sports analytics modules (arbitrage / EV / line movement).

Covers the pure-math helpers (2-way and 3-way arbitrage detection,
no-vig fair probability, EV math) with fixed odds fixtures, plus the async
public functions with mocked ``sports_data.odds`` feeds: detection,
threshold filtering, sorting, and the never-raise contract. Line-movement
history is reset per test; all feeds are mocked — no live network.
"""

from __future__ import annotations

from typing import Any

import pytest

import datasets.sports_data.arbitrage as arbitrage
import datasets.sports_data.ev as ev
import datasets.sports_data.line_movement as line_movement

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_line_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the in-memory line-movement history between tests."""
    monkeypatch.setattr(line_movement, "_history", {})


def _odds_record(
    sport: str,
    event: str,
    event_id: str,
    book: str,
    home: float | None,
    away: float | None,
) -> dict[str, Any]:
    return {
        "sport": sport,
        "event": event,
        "event_id": event_id,
        "market": "h2h",
        "bookmaker": book,
        "home_odds": home,
        "away_odds": away,
    }


def _arb_records() -> list[dict[str, Any]]:
    """One 2-way arb (DK home 2.10 vs FD away 2.10) + one fair event."""
    return [
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.10, 1.80),
        _odds_record("nba", "Celtics @ Lakers", "e1", "FanDuel", 1.95, 2.10),
        _odds_record("nfl", "Bears @ Packers", "e2", "DraftKings", 2.00, 2.00),
    ]


def _ev_records() -> list[dict[str, Any]]:
    """Pinnacle fair 50/50; FanDuel away +10% EV, Barstool away +2.5%."""
    return [
        _odds_record("nba", "Celtics @ Lakers", "e1", "Pinnacle", 2.00, 2.00),
        _odds_record("nba", "Celtics @ Lakers", "e1", "FanDuel", 1.95, 2.20),
        _odds_record("nba", "Celtics @ Lakers", "e1", "Barstool", 1.90, 2.05),
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.02, 1.98),
    ]


def _comparison(home_price: float, away_price: float) -> dict[str, Any]:
    """A get_event_odds comparison dict with one DraftKings h2h market."""
    return {
        "event_id": "eid123",
        "sport": "nba",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": home_price},
                            {"name": "Los Angeles Lakers", "price": away_price},
                        ],
                    }
                ],
            }
        ],
        "source": "the_odds_api",
    }


# ── detect_2way_arb ───────────────────────────────────────────────────


def test_detect_2way_arb_yes() -> None:
    result = arbitrage.detect_2way_arb(2.10, 2.10)
    assert result is not None
    assert result["market"] == "h2h"
    assert result["total_implied"] == pytest.approx(0.9524, abs=1e-3)
    assert result["arb_yield_pct"] == pytest.approx(5.0, abs=0.1)
    assert result["stake_split"]["home_pct"] == pytest.approx(50.0, abs=0.01)
    assert result["stake_split"]["away_pct"] == pytest.approx(50.0, abs=0.01)


def test_detect_2way_arb_dict_shape() -> None:
    result = arbitrage.detect_2way_arb(
        {"book": "DraftKings", "odds": 2.10}, {"book": "FanDuel", "odds": 2.10}
    )
    assert result is not None
    expected = {"book": "DraftKings", "odds": 2.10}
    assert result["books"]["home"] == expected
    expected_2 = {"book": "FanDuel", "odds": 2.10}
    assert result["books"]["away"] == expected_2


def test_detect_2way_arb_no_arb() -> None:
    assert arbitrage.detect_2way_arb(2.0, 2.0) is None  # sum of implied == 1.0


def test_detect_2way_arb_invalid_inputs() -> None:
    assert arbitrage.detect_2way_arb(1.0, 2.0) is None  # odds must exceed 1
    assert arbitrage.detect_2way_arb(None, 2.0) is None
    assert arbitrage.detect_2way_arb("junk", 2.0) is None


# ── detect_3way_arb ───────────────────────────────────────────────────


def test_detect_3way_arb_yes() -> None:
    result = arbitrage.detect_3way_arb(3.5, 3.5, 3.5)
    assert result is not None
    assert result["market"] == "h2h_3way"
    assert result["total_implied"] == pytest.approx(0.8571, abs=1e-3)
    assert result["arb_yield_pct"] == pytest.approx(16.67, abs=0.1)
    for key in ("home_pct", "away_pct", "draw_pct"):
        assert result["stake_split"][key] == pytest.approx(33.33, abs=0.1)


def test_detect_3way_arb_no_arb() -> None:
    assert arbitrage.detect_3way_arb(3.0, 3.0, 3.0) is None  # sum of implied == 1.0


# ── compute_no_vig ────────────────────────────────────────────────────


def test_compute_no_vig_even_line() -> None:
    fair = ev.compute_no_vig(2.0, 2.0)
    assert fair["home_prob"] == pytest.approx(0.5)
    assert fair["away_prob"] == pytest.approx(0.5)
    assert fair["margin"] == pytest.approx(0.0)
    assert fair["fair_home_odds"] == pytest.approx(2.0)
    assert fair["fair_away_odds"] == pytest.approx(2.0)


def test_compute_no_vig_removes_margin() -> None:
    fair = ev.compute_no_vig(1.91, 1.91)
    assert fair["margin"] == pytest.approx(0.0471, abs=1e-3)
    assert fair["home_prob"] == pytest.approx(0.5, abs=1e-6)
    assert fair["fair_home_odds"] == pytest.approx(2.0, abs=1e-3)


def test_compute_no_vig_invalid_inputs() -> None:
    bad = ev.compute_no_vig(None, 2.0)
    assert bad["home_prob"] is None
    assert bad["away_prob"] is None
    bad = ev.compute_no_vig(1.0, 2.0)
    assert bad["home_prob"] is None
    assert bad["margin"] is None


# ── find_arbitrage ────────────────────────────────────────────────────


async def test_find_arbitrage_detects_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return _arb_records()

    monkeypatch.setattr(arbitrage, "_get_odds", fake)
    results = await arbitrage.find_arbitrage(min_yield_pct=0.5)
    assert len(results) == 1
    top = results[0]
    assert top["event"] == "Celtics @ Lakers"
    assert top["sport"] == "nba"
    assert top["market"] == "h2h"
    expected = {"book": "DraftKings", "odds": 2.10}
    assert top["books"]["home"] == expected
    expected_2 = {"book": "FanDuel", "odds": 2.10}
    assert top["books"]["away"] == expected_2
    assert top["arb_yield_pct"] == pytest.approx(5.0, abs=0.1)


async def test_find_arbitrage_threshold_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return _arb_records()

    monkeypatch.setattr(arbitrage, "_get_odds", fake)
    assert await arbitrage.find_arbitrage(min_yield_pct=10.0) == []


async def test_find_arbitrage_no_opportunities() -> None:
    records = [_odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.0, 2.0)]

    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return records

    assert await arbitrage.find_arbitrage() == []


async def test_find_arbitrage_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        raise RuntimeError("feed down")

    monkeypatch.setattr(arbitrage, "_get_odds", boom)
    assert await arbitrage.find_arbitrage() == []


# ── find_plus_ev ──────────────────────────────────────────────────────


async def test_find_plus_ev_detects_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return _ev_records()

    monkeypatch.setattr(ev, "_get_odds", fake)
    results = await ev.find_plus_ev(min_ev_pct=2.0)
    assert len(results) == 2
    top, second = results[0], results[1]
    assert top["book"] == "FanDuel"
    assert top["side"] == "away"
    assert top["odds"] == 2.20
    assert top["fair_prob"] == pytest.approx(0.5, abs=1e-6)
    assert top["implied_prob"] == pytest.approx(0.4545, abs=1e-3)
    assert top["ev_pct"] == pytest.approx(10.0, abs=0.1)
    assert second["book"] == "Barstool"
    assert second["ev_pct"] == pytest.approx(2.5, abs=0.1)
    assert top["ev_pct"] > second["ev_pct"]


async def test_find_plus_ev_min_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return _ev_records()

    monkeypatch.setattr(ev, "_get_odds", fake)
    assert await ev.find_plus_ev(min_ev_pct=20.0) == []


async def test_find_plus_ev_no_sharp_book() -> None:
    records = [_odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.0, 2.0)]

    async def fake(sport: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        return records

    assert await ev.find_plus_ev() == []


# ── get_line_movement ─────────────────────────────────────────────────


async def test_line_movement_records_and_sharp_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake(event_id: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _comparison(1.85, 2.10)
        return _comparison(2.05, 2.10)  # Celtics 1.85 -> 2.05 (+10.8%)

    monkeypatch.setattr(line_movement, "_get_event_odds", fake)
    first = await line_movement.get_line_movement("eid123")
    assert first["movements"] == []
    assert first["sharp_signal"] is False

    second = await line_movement.get_line_movement("eid123")
    assert second["event"] == "Boston Celtics @ Los Angeles Lakers"
    assert second["market"] == "h2h"
    assert len(second["movements"]) == 1
    move = second["movements"][0]
    assert move["book"] == "DraftKings"
    assert move["outcome"] == "Boston Celtics"
    assert move["from_odds"] == pytest.approx(1.85)
    assert move["to_odds"] == pytest.approx(2.05)
    assert move["at"]
    assert second["sharp_signal"] is True


async def test_line_movement_no_change_no_movements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(event_id: str) -> dict[str, Any]:
        return _comparison(1.85, 2.10)

    monkeypatch.setattr(line_movement, "_get_event_odds", fake)
    await line_movement.get_line_movement("eid123")
    result = await line_movement.get_line_movement("eid123")
    assert result["movements"] == []
    assert result["sharp_signal"] is False


async def test_line_movement_unknown_event() -> None:
    async def fake(event_id: str) -> dict[str, Any]:
        return {}

    assert await line_movement.get_line_movement("nope") == {}


async def test_line_movement_empty_id() -> None:
    assert await line_movement.get_line_movement("  ") == {}
