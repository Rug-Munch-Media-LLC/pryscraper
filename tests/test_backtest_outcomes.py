"""The join and the ESPN adapter must be honest: match, settle, or refuse.

Six load-bearing cases: a clean join on ``event_id``, a date/teams fallback when
ids differ, an unmatched odds row aborting the exporter with exit ``2``, a
duplicate id refusing on either side, moneyline ``won`` derived from scores for
home/away/tie, and the fixture-driven ESPN adapter (scoreboard + open/close
prices) settling one real recorded game.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
for path in (str(_SCRIPTS), str(_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import backtest_join as join_mod  # noqa: E402
import export_backtest_series as export  # noqa: E402
import pytest  # noqa: E402

FIXTURES = _ROOT / "datasets" / "sports_data" / "fixtures"
ODDS_HEADER = "event_id,ts,odds,closing_odds,side,date,home,away\n"


def _csv(path: Path, header: str, rows: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + rows, encoding="utf-8")
    return path


def _odds(tmp: Path, rows: str) -> Path:
    return _csv(tmp / "odds.csv", ODDS_HEADER, rows)


def _outcomes(tmp: Path, rows: list[dict]) -> Path:
    path = tmp / "outcomes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_join_on_event_id_and_date_fallback(tmp_path: Path) -> None:
    odds = _odds(
        tmp_path,
        "a1,1700000000,2.00,1.90,home,2026-04-10,Hornets,Pistons\n"
        "a2,1700003600,1.80,1.75,home,2026-04-11,Knicks,76ers\n",
    )
    outcomes = _outcomes(
        tmp_path,
        [
            {"event_id": "a1", "home_score": 110, "away_score": 100},
            # fallback: id differs, but the date + teams match row a2
            {
                "event_id": "zzz",
                "date": "2026-04-11",
                "home": "knicks",
                "away": "76ers",
                "home_score": 90,
                "away_score": 95,
            },
        ],
    )
    events, pushes = join_mod.load_series(odds, outcomes)
    assert pushes == 0
    assert [(e.event_id, e.won) for e in events] == [("a1", True), ("a2", False)]
    assert events[0].odds == 2.0
    assert events[0].closing_odds == 1.9


def test_unmatched_event_exits_two(tmp_path: Path) -> None:
    odds = _odds(
        tmp_path,
        "a1,1700000000,2.00,1.90,home,2026-04-10,Hornets,Pistons\n"
        "orphan,1700003600,1.8,1.7,home,2026-04-11,X,Y\n",
    )
    outcomes = _outcomes(tmp_path, [{"event_id": "a1", "home_score": 110, "away_score": 100}])
    with pytest.raises(join_mod.JoinError, match="orphan"):
        join_mod.load_series(odds, outcomes)
    code = export.main(
        ["--input", str(odds), "--outcomes", str(outcomes), "--out", str(tmp_path / "o.csv")]
    )
    assert code == 2
    assert not (tmp_path / "o.csv").exists()


def test_duplicate_ids_refused_on_both_sides(tmp_path: Path) -> None:
    good = _outcomes(tmp_path, [{"event_id": "a1", "home_score": 1, "away_score": 0}])
    dup_odds = _odds(tmp_path, "a1,1,2.0,1.9,home,2026-04-10,H,A\na1,2,2.0,1.9,home,2026-04-11,H,A\n")
    dup_out = _outcomes(
        tmp_path / "dup",
        [{"event_id": "a1", "home_score": 1, "away_score": 0},
         {"event_id": "a1", "home_score": 2, "away_score": 0}],
    )
    with pytest.raises(join_mod.JoinError, match="duplicate"):
        join_mod.load_series(dup_odds, good)
    with pytest.raises(join_mod.JoinError, match="duplicate"):
        join_mod.load_series(_odds(tmp_path / "ok", "a1,1,2.0,1.9,home,2026-04-10,H,A\n"), dup_out)


def test_derive_won_home_away_tie() -> None:
    results = join_mod.results_module()
    assert results.derive_won(110, 100, "home") is True
    assert results.derive_won(110, 100, "away") is False
    assert results.derive_won(95, 95, "home") is None
    assert results.derive_won(95, 95, "away") is None


def test_tie_is_counted_as_a_push_not_a_loss(tmp_path: Path) -> None:
    odds = _odds(tmp_path, "a1,1,2.0,1.9,home,2026-04-10,H,A\n")
    outcomes = _outcomes(tmp_path, [{"event_id": "a1", "home_score": 95, "away_score": 95}])
    with pytest.raises(join_mod.JoinError, match="push"):
        join_mod.load_series(odds, outcomes)


def _assert_known_game(game: dict) -> None:
    assert game["home"] == "Charlotte Hornets"
    assert game["away"] == "Detroit Pistons"
    assert (game["home_score"], game["away_score"]) == (100, 118)


def _assert_known_prices(home: dict, away: dict) -> None:
    assert (home["odds"], home["closing_odds"]) == (1.74, 1.45)
    assert (away["odds"], away["closing_odds"]) == (2.14, 2.8)


def test_fixture_adapter_parses_scores_and_prices() -> None:
    results = join_mod.results_module()
    board = json.loads((FIXTURES / "espn_scoreboard_nba_20260410.json").read_text())
    games = results.parse_scoreboard(board)
    assert games, "fixture has no completed game"
    game = next(g for g in games if g["event_id"] == "401811026")
    _assert_known_game(game)

    odds = json.loads((FIXTURES / "espn_odds_100_nba_401811026.json").read_text())
    home = results.parse_moneyline(odds, "home")
    away = results.parse_moneyline(odds, "away")
    _assert_known_prices(home, away)
    assert results.derive_won(game["home_score"], game["away_score"], "home") is False
    assert results.derive_won(game["home_score"], game["away_score"], "away") is True

    # the recorded pair joins to a settled bet, in memory
    row = {
        "event_id": game["event_id"], "ts": game["date"],
        "odds": home["odds"], "closing_odds": home["closing_odds"],
        "side": "home", "date": game["date"], "home": game["home"], "away": game["away"],
    }
    outcome = {"event_id": game["event_id"], "home_score": game["home_score"],
               "away_score": game["away_score"]}
    events, _ = join_mod.join([row], {game["event_id"]: outcome})
    assert events[0].won is False
    assert events[0].odds == 1.74
