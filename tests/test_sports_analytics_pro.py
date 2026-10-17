# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the pro analytics modules (CLV / projections / exports).

Covers the pure-math CLV helper, the event-level CLV tracker with mocked
odds + closing-line feeds, the honest season-average projections with mocked
player stats, the model-ready dataset exporter (CSV/JSON content, parquet
degradation when pyarrow is absent, unsupported formats, never-raise), and
the minimal CLV backtest harness over synthetic records. All feeds are
mocked — no live network, no API keys.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest

import datasets.sports_data.clv as clv
import datasets.sports_data.exports as exports
import datasets.sports_data.projections as projections

# ── Shared fixtures / builders ─────────────────────────────────────────


def _odds_record(
    sport: str,
    event: str,
    event_id: str,
    book: str,
    home_odds: float | None,
    away_odds: float | None,
    **extra: Any,
) -> dict[str, Any]:
    """A canonical odds record as produced by sports_data.odds._record."""
    record: dict[str, Any] = {
        "sport": sport,
        "event": event,
        "event_id": event_id,
        "market": "h2h",
        "book": book,
        "bookmaker": book,
        "home": "Boston Celtics",
        "away": "Los Angeles Lakers",
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": "2026-08-16T18:00:00Z",
        "source": "the_odds_api",
    }
    record.update(extra)
    return record


def _comparison(book_prices: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """A get_event_odds comparison with h2h markets per book title."""
    bookmakers = []
    for title, (home_price, away_price) in book_prices.items():
        bookmakers.append(
            {
                "key": title.lower().replace(" ", ""),
                "title": title,
                "book": title.lower(),
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
        )
    return {
        "event_id": "eid123",
        "sport": "nba",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "commence_time": "2026-08-16T23:00:00Z",
        "bookmakers": bookmakers,
        "source": "the_odds_api",
    }


def _closing_line(closing: dict[str, dict[str, float]]) -> dict[str, Any]:
    """A get_closing_line payload keyed by book title."""
    return {
        "event_id": "eid123",
        "sport": "nba",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "closing": closing,
        "best": {},
        "source": "the_odds_api",
    }


def _stats_record(stats: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A get_player_stats record."""
    record: dict[str, Any] = {
        "player": "LeBron James",
        "sport": "nba",
        "team": "Los Angeles Lakers",
        "position": "F",
        "season": "2025-26",
        "stats": stats,
        "source": "espn",
    }
    record.update(extra)
    return record


# ── compute_clv (pure math) ────────────────────────────────────────────


def test_compute_clv_beats_close() -> None:
    result = clv.compute_clv(2.10, 2.00)
    assert result["clv_pct"] == pytest.approx(5.0, abs=1e-3)
    assert result["edge_pct"] == pytest.approx(2.381, abs=1e-2)
    assert result["bet_odds"] == pytest.approx(2.10)
    assert result["closing_odds"] == pytest.approx(2.00)


def test_compute_clv_worse_than_close() -> None:
    result = clv.compute_clv(1.90, 2.00)
    assert result["clv_pct"] == pytest.approx(-5.0, abs=1e-3)
    assert result["edge_pct"] == pytest.approx(-2.632, abs=1e-2)


def test_compute_clv_no_move() -> None:
    result = clv.compute_clv(2.00, 2.00)
    assert result["clv_pct"] == pytest.approx(0.0)
    assert result["edge_pct"] == pytest.approx(0.0)


def test_compute_clv_edge_equals_implied_delta() -> None:
    result = clv.compute_clv(2.20, 1.95)
    expected_edge = (1.0 / 1.95 - 1.0 / 2.20) * 100.0
    assert result["edge_pct"] == pytest.approx(expected_edge, abs=1e-3)


def test_compute_clv_invalid_inputs() -> None:
    for bad in ("garbage", None, 0.9, 1.0, -3):
        result = clv.compute_clv(bad, 2.0)
        assert result["clv_pct"] is None
        assert result["edge_pct"] is None
    result = clv.compute_clv(2.0, "nope")
    assert result["clv_pct"] is None


# ── track_clv (mocked feeds) ───────────────────────────────────────────


@pytest.fixture
def mock_clv_feeds(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Point clv's guarded imports at controllable fakes."""
    state: dict[str, Any] = {}

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return state.get("comparison", {})

    async def fake_closing_line(event_id: str) -> dict[str, Any]:
        return state.get("closing", {})

    monkeypatch.setattr(clv, "_get_event_odds", fake_event_odds)
    monkeypatch.setattr(clv, "_get_closing_line", fake_closing_line)
    return state


async def test_track_clv_records_per_book_side(mock_clv_feeds: dict[str, Any]) -> None:
    mock_clv_feeds["comparison"] = _comparison({"DraftKings": (2.05, 1.95)})
    mock_clv_feeds["closing"] = _closing_line({"DraftKings": {"home": 2.00, "away": 1.90}})
    records = await clv.track_clv("eid123")
    assert len(records) == 2
    by_side = {record["side"]: record for record in records}
    expected = {"home", "away"}
    assert set(by_side) == expected
    assert by_side["home"]["book"] == "DraftKings"
    assert by_side["home"]["bet_odds"] == pytest.approx(2.05)
    assert by_side["home"]["closing_odds"] == pytest.approx(2.00)
    assert by_side["home"]["clv_pct"] == pytest.approx(2.5, abs=1e-3)
    assert by_side["home"]["edge_pct"] == pytest.approx(1.2195, abs=1e-2)
    assert by_side["away"]["clv_pct"] == pytest.approx(2.6316, abs=1e-3)
    assert by_side["home"]["outcome"] == "Boston Celtics"
    assert records[0]["event_id"] == "eid123"
    assert records[0]["market"] == "h2h"


async def test_track_clv_sorted_by_book(mock_clv_feeds: dict[str, Any]) -> None:
    mock_clv_feeds["comparison"] = _comparison(
        {"Zeta Bet": (2.10, 1.80), "Alpha Bet": (2.10, 1.80)}
    )
    mock_clv_feeds["closing"] = _closing_line(
        {"Zeta Bet": {"home": 2.00, "away": 1.75}, "Alpha Bet": {"home": 2.00, "away": 1.75}}
    )
    records = await clv.track_clv("eid123")
    books = [record["book"] for record in records]
    assert books == sorted(books)
    assert books[0] == "Alpha Bet"


async def test_track_clv_skips_books_without_closing(mock_clv_feeds: dict[str, Any]) -> None:
    mock_clv_feeds["comparison"] = _comparison(
        {"DraftKings": (2.05, 1.95), "Barstool": (2.10, 1.90)}
    )
    # Only DraftKings has a closing line -> Barstool rows are skipped.
    mock_clv_feeds["closing"] = _closing_line({"DraftKings": {"home": 2.00, "away": 1.90}})
    records = await clv.track_clv("eid123")
    assert all(record["book"] == "DraftKings" for record in records)


async def test_track_clv_unknown_event(mock_clv_feeds: dict[str, Any]) -> None:
    mock_clv_feeds["comparison"] = {}
    assert await clv.track_clv("eid123") == []


async def test_track_clv_no_closing_line(mock_clv_feeds: dict[str, Any]) -> None:
    mock_clv_feeds["comparison"] = _comparison({"DraftKings": (2.05, 1.95)})
    mock_clv_feeds["closing"] = {}
    assert await clv.track_clv("eid123") == []


async def test_track_clv_empty_event_id(mock_clv_feeds: dict[str, Any]) -> None:
    assert await clv.track_clv("") == []
    assert await clv.track_clv(None) == []  # type: ignore[arg-type]


async def test_track_clv_never_raises(mock_clv_feeds: dict[str, Any]) -> None:
    async def boom(event_id: str) -> dict[str, Any]:
        raise RuntimeError("network down")

    mock_clv_feeds["comparison"] = _comparison({"DraftKings": (2.05, 1.95)})
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(clv, "_get_closing_line", boom)
    try:
        assert await clv.track_clv("eid123") == []
    finally:
        monkeypatch.undo()


# ── project_player_prop (mocked stats) ─────────────────────────────────


@pytest.fixture
def mock_stats(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Point projections' guarded stats import at a controllable fake."""
    state: dict[str, Any] = {}

    async def fake_stats(player: str, sport: str) -> dict[str, Any]:
        return state.get("record", {})

    monkeypatch.setattr(projections, "_get_player_stats", fake_stats)
    return state


async def test_project_points(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    result = await projections.project_player_prop("LeBron James", "points", "nba")
    assert result["player"] == "LeBron James"
    assert result["market"] == "points"
    assert result["sport"] == "nba"
    assert result["projected_line"] == pytest.approx(24.4)
    assert result["season_avg"] == pytest.approx(24.4)
    assert result["last_5_avg"] == pytest.approx(24.4)  # honest fallback
    assert result["matchup_factor"] == pytest.approx(1.0)
    assert result["source"] == "projection"
    assert isinstance(result["confidence"], int)
    assert 0 <= result["confidence"] <= 100


async def test_project_matchup_factor(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    result = await projections.project_player_prop(
        "LeBron James", "points", "nba", matchup_factor=0.9
    )
    assert result["matchup_factor"] == pytest.approx(0.9)
    assert result["projected_line"] == pytest.approx(21.96, abs=1e-2)


async def test_project_matchup_factor_clamped(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    result = await projections.project_player_prop(
        "LeBron James", "points", "nba", matchup_factor=99.0
    )
    assert result["matchup_factor"] == pytest.approx(1.5)


async def test_project_uses_last_5_when_present(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record(
        {"Points Per Game": "24.4", "Last 5 Points Per Game": "28.0"}
    )
    result = await projections.project_player_prop("LeBron James", "points", "nba")
    assert result["last_5_avg"] == pytest.approx(28.0)
    assert result["basis"] == "season average + last-5 recency"


async def test_project_substring_stat_match(mock_stats: dict[str, Any]) -> None:
    # ESPN payload keys vary; substring matching on the primary label must
    # find the value even when the exact key is absent.
    mock_stats["record"] = _stats_record({"PPG": "31.2"})
    result = await projections.project_player_prop("LeBron James", "points", "nba")
    assert result["season_avg"] == pytest.approx(31.2)


async def test_project_pra_derived_sum(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record(
        {
            "Points Per Game": "24.4",
            "Rebounds Per Game": "10.1",
            "Assists Per Game": "7.2",
        }
    )
    result = await projections.project_player_prop("LeBron James", "pra", "nba")
    assert result["season_avg"] == pytest.approx(41.7, abs=1e-2)
    assert result["projected_line"] == pytest.approx(41.7, abs=1e-2)


async def test_project_pra_missing_component(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    assert await projections.project_player_prop("LeBron James", "pra", "nba") == {}


async def test_project_unknown_market(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    assert await projections.project_player_prop("LeBron James", "double-doubles", "nba") == {}


async def test_project_unknown_player(mock_stats: dict[str, Any]) -> None:
    mock_stats["record"] = {}
    assert await projections.project_player_prop("Nobody", "points", "nba") == {}


async def test_project_never_raises(mock_stats: dict[str, Any]) -> None:
    async def boom(player: str, sport: str) -> dict[str, Any]:
        raise RuntimeError("stats down")

    mock_stats["record"] = _stats_record({"Points Per Game": "24.4"})
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(projections, "_get_player_stats", boom)
    try:
        assert await projections.project_player_prop("LeBron James", "points", "nba") == {}
    finally:
        monkeypatch.undo()


# ── export_dataset (mocked odds) ───────────────────────────────────────


@pytest.fixture
def mock_export_odds(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Point exports' guarded odds import at a controllable fake."""
    state: dict[str, Any] = {}

    async def fake_odds(**kwargs: Any) -> list[dict[str, Any]]:
        return state.get("records", [])

    monkeypatch.setattr(exports, "_get_odds", fake_odds)
    return state


async def test_export_csv(mock_export_odds: dict[str, Any]) -> None:
    mock_export_odds["records"] = [
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.10, 1.80)
    ]
    result = await exports.export_dataset("nba", market="h2h", format="csv")
    assert result["format"] == "csv"
    assert result["rows"] == 1
    assert result["columns"] == exports._EXPORT_COLUMNS
    payload = result["payload_or_path"]
    assert isinstance(payload, str)
    rows = list(csv.DictReader(io.StringIO(payload)))
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "Celtics @ Lakers"
    assert float(row["home_odds"]) == pytest.approx(2.10)
    assert float(row["implied_home"]) == pytest.approx(1 / 2.10, abs=1e-4)
    assert float(row["fair_home_prob"]) == pytest.approx(0.4615, abs=1e-3)
    assert float(row["ev_home_pct"]) == pytest.approx(-3.08, abs=0.2)


async def test_export_json(mock_export_odds: dict[str, Any]) -> None:
    mock_export_odds["records"] = [
        _odds_record("nba", "Celtics @ Lakers", "e1", "Pinnacle", 2.00, 2.00),
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.10, 1.90),
    ]
    result = await exports.export_dataset("nba", market="h2h", format="json")
    assert result["format"] == "json"
    assert result["rows"] == 2
    rows = json.loads(result["payload_or_path"])
    assert len(rows) == 2
    expected = {"Pinnacle", "DraftKings"}
    assert {row["book"] for row in rows} == expected
    assert "implied_away" in rows[0]
    assert "ev_away_pct" in rows[0]


async def test_export_json_clv_columns_when_closing_present(
    mock_export_odds: dict[str, Any],
) -> None:
    mock_export_odds["records"] = [
        _odds_record(
            "nba",
            "Celtics @ Lakers",
            "e1",
            "DraftKings",
            2.10,
            1.90,
            closing_home_odds=2.00,
            closing_away_odds=2.00,
        )
    ]
    result = await exports.export_dataset("nba", format="json")
    rows = json.loads(result["payload_or_path"])
    assert rows[0]["clv_home_pct"] == pytest.approx(5.0, abs=1e-2)
    assert rows[0]["clv_away_pct"] == pytest.approx(-5.0, abs=1e-2)


async def test_export_parquet_degrades_without_pyarrow(
    mock_export_odds: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exports, "pa", None)
    monkeypatch.setattr(exports, "pq", None)
    mock_export_odds["records"] = [
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.10, 1.80)
    ]
    result = await exports.export_dataset("nba", format="parquet")
    assert result["format"] == "json"
    assert result["degraded_from"] == "parquet"
    assert result["rows"] == 1
    rows = json.loads(result["payload_or_path"])
    assert len(rows) == 1


async def test_export_unsupported_format(mock_export_odds: dict[str, Any]) -> None:
    mock_export_odds["records"] = [_odds_record("nba", "Celtics @ Lakers", "e1", "DK", 2.0, 2.0)]
    result = await exports.export_dataset("nba", format="xml")
    assert result["rows"] == 0
    assert "unsupported format" in result["error"]


async def test_export_no_records(mock_export_odds: dict[str, Any]) -> None:
    mock_export_odds["records"] = []
    result = await exports.export_dataset("nba", format="csv")
    assert result["rows"] == 0
    assert "no odds records" in result["error"]


async def test_export_never_raises(mock_export_odds: dict[str, Any]) -> None:
    async def boom(**kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("odds down")

    mock_export_odds["records"] = [_odds_record("nba", "Celtics @ Lakers", "e1", "DK", 2.0, 2.0)]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(exports, "_get_odds", boom)
    try:
        result = await exports.export_dataset("nba", format="csv")
        assert result["rows"] == 0
        assert "no odds records" in result["error"]
    finally:
        monkeypatch.undo()


# ── backtest (synthetic records) ───────────────────────────────────────


def _bet(bet_odds: float, closing_odds: float, result: Any = None) -> dict[str, Any]:
    return {"bet_odds": bet_odds, "closing_odds": closing_odds, "result": result}


async def test_backtest_closing_line_strategy() -> None:
    result = await exports.backtest(
        "nba",
        strategy="closing_line",
        threshold_pct=5.0,
        records=[
            _bet(2.10, 2.00, 1.0),  # clv 5.0% -> bet, win  -> +1.10
            _bet(2.20, 2.00, 0.0),  # clv 10.0% -> bet, loss -> -1.00
            _bet(2.05, 2.00, 1.0),  # clv 2.5% < threshold -> skipped
            _bet(2.10, 2.00, None),  # clv 5.0% -> bet, unsettled
        ],
    )
    assert result["strategy"] == "closing_line"
    assert result["bets"] == 3
    assert result["settled"] == 2
    assert result["wins"] == 1
    assert result["win_rate"] == pytest.approx(0.5)
    assert result["roi_pct"] == pytest.approx(5.0, abs=1e-3)  # (1.10 - 1.00) / 2
    # ev_per_bet = mean((2.10/2-1), (2.20/2-1), (2.10/2-1)) = (0.05+0.10+0.05)/3
    assert result["ev_per_bet"] == pytest.approx(0.066667, abs=1e-4)
    assert result["source"] == "synthetic"


async def test_backtest_threshold_filters() -> None:
    result = await exports.backtest(
        "nba",
        threshold_pct=10.0,
        records=[
            _bet(2.10, 2.00, 1.0),  # clv 5.0% -> skipped
            _bet(2.20, 2.00, 1.0),  # clv 10.0% -> bet, win
        ],
    )
    assert result["bets"] == 1
    assert result["win_rate"] == pytest.approx(1.0)


async def test_backtest_no_qualifying_bets() -> None:
    result = await exports.backtest(
        "nba",
        threshold_pct=5.0,
        records=[_bet(2.00, 2.00, 1.0), _bet(2.01, 2.00, 0.0)],
    )
    assert result["bets"] == 0
    assert result["win_rate"] is None
    assert result["roi_pct"] is None
    assert result["ev_per_bet"] is None


async def test_backtest_unsupported_strategy() -> None:
    result = await exports.backtest("nba", strategy="fade_the_sharp")
    assert result["bets"] == 0
    assert "unsupported strategy" in result["error"]


async def test_backtest_garbage_records_never_raise() -> None:
    result = await exports.backtest("nba", records=[None, {"bet_odds": "x"}, "junk", 42])  # type: ignore[list-item]
    assert result["bets"] == 0
    assert result["win_rate"] is None


async def test_backtest_live_fallback_zero_bets(
    mock_export_odds: dict[str, Any],
) -> None:
    # Live odds carry no closing line -> nothing can qualify.
    mock_export_odds["records"] = [
        _odds_record("nba", "Celtics @ Lakers", "e1", "DraftKings", 2.10, 1.80)
    ]
    result = await exports.backtest("nba", records=None)
    assert result["bets"] == 0
    assert result["source"] == "live"
