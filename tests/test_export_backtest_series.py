"""The exporter must not fabricate an outcome, and must round-trip a real one.

Four load-bearing cases: the canonical CSV survives a load/save round trip, a
duplicate id is refused instead of silently deduplicated, the fingerprint is a
stable function of the series, and the harness itself accepts the exported file.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import backtest_strategy as cli  # noqa: E402
import export_backtest_series as export  # noqa: E402
from backtest_data import generate_synthetic, load_csv  # noqa: E402

HEADER = "event_id,ts,odds,closing_odds,won,prob\n"


def _write(path: Path, rows: str) -> Path:
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def _series(tmp_path: Path, n: int = 12) -> Path:
    out = tmp_path / "series.csv"
    assert export.main(["--synthetic", "--events", str(n), "--out", str(out)]) == 0
    return out


def test_round_trip_preserves_schema_and_values(tmp_path: Path) -> None:
    out = _series(tmp_path)
    assert out.read_text(encoding="utf-8").splitlines()[0] == HEADER.strip()
    events = load_csv(out)
    source = generate_synthetic(12, seed=7)
    assert [e.event_id for e in events] == [e.event_id for e in source]
    assert [e.won for e in events] == [e.won for e in source]
    assert all(e.features for e in events)
    for got, want in zip(events, source, strict=True):
        assert abs(got.ts - want.ts) < 1e-6
        assert abs(got.odds - want.odds) < 1e-4
        assert abs(got.closing_odds - want.closing_odds) < 1e-4


def test_duplicate_event_id_is_refused(tmp_path: Path) -> None:
    dup = _write(
        tmp_path / "dup.csv",
        "e1,1700000000,2.0,1.95,1,0.55\ne1,1700003600,2.1,2.00,0,0.54\n",
    )
    out = tmp_path / "out.csv"
    assert export.main(["--input", str(dup), "--out", str(out)]) == export.EXIT_UNMEASURABLE
    assert not out.exists()


def test_fingerprint_is_stable_and_data_dependent(tmp_path: Path) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    for path in (first, second):
        assert export.main(["--synthetic", "--events", "20", "--out", str(path)]) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    changed = tmp_path / "c.csv"
    assert export.main(["--synthetic", "--events", "21", "--out", str(changed)]) == 0
    assert first.read_text(encoding="utf-8") != changed.read_text(encoding="utf-8")


def test_export_requires_a_real_source(tmp_path: Path) -> None:
    out = tmp_path / "none.csv"
    assert export.main(["--out", str(out)]) == export.EXIT_UNMEASURABLE
    assert not out.exists()


def test_harness_accepts_the_exported_file(tmp_path: Path) -> None:
    out = _series(tmp_path, n=600)
    assert cli.main(["--csv", str(out), "--train", "300", "--test", "150"]) == 0
