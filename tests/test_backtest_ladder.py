"""Ladder backtest: the median, the warm-up shape, and the two exit codes.

The two exit codes are the point of this file. The harness used to return 0 on
every outcome, so a run where all ten sources came back ConnectError was
indistinguishable from a total ladder regression, and a CI gate keying on the
exit code passed a completely broken ladder. These tests prove the two verdicts
now separate, and that the median which stopped a lucky single run being
committed as a baseline is still the number the summary records.

No network. The probe is stubbed; the aggregation half is pure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package; the CLI and its modules import each other by bare
# name, so scripts/ must be on sys.path BEFORE either is imported.
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import backtest_ladder as cli  # noqa: E402
import ladder_aggregate as agg  # noqa: E402

from tests.ladder_harness import _dead, _fail, _ok  # noqa: E402


def test_p95_is_never_below_p50() -> None:
    """The off-by-one that made p95 smaller than the median.

    `sorted(latencies)[int(len*0.95) - 1]` returned index 0 for n=2, so the
    "95th percentile" was the MINIMUM and p95 < p50 held for any two-point set.
    The nearest-rank estimate must be >= p50 for every n.
    """
    for n in range(1, 30):
        run = [_ok(f"https://{i}.example/", ms=float(i)) for i in range(n)]
        summary = agg.summarise(run, [1.0])
        assert summary["p95_ms"] >= summary["p50_ms"], f"p95 < p50 at n={n}"

    two = [_ok("https://a.example/", ms=100.0), _ok("https://b.example/", ms=50.0)]
    assert agg.summarise(two, [1.0])["p95_ms"] == 100.0


def test_offline_replay_is_deterministic() -> None:
    """Replaying the same fixture twice must produce identical summaries.

    Determinism is the whole point of the offline path: the live probe is
    nondeterministic (latency and success vary run to run), so grading the
    committed per-source fixture is the only way to get a reproducible number.
    """
    run = [_ok("https://a.example/", ms=5.0), _fail("https://b.example/")]
    a = agg.offline_summary(run, 3)
    b = agg.offline_summary(run, 3)

    assert a == b
    assert a["success_rate"] == 0.5
    assert a["success_rate_observed"]["runs"] == 3


def test_offline_without_a_fixture_is_unmeasurable(capsys) -> None:
    """No fixture is a fail-loud, not a fabricated pass."""
    original = cli.read_results
    cli.read_results = lambda path=None: []
    try:
        assert cli._offline(["--offline"]) == cli.EXIT_UNMEASURABLE
    finally:
        cli.read_results = original

    assert "UNMEASURABLE" in capsys.readouterr().out


def test_summary_records_the_median_not_the_last_run() -> None:
    """The 2026-08-29 incident, pinned.

    Three warm runs of an UNCHANGED ladder gave 0.875 / 0.875 / 1.0. The 1.0 was
    committed as the baseline, and the next run returning 0.75 read as a
    regression. The number that must be recorded is the MEDIAN, so a favourable
    run cannot become the baseline.
    """
    # 16 sources so 14/16 == 0.875 exactly, matching the real 2026-08-29
    # observation of 0.875 / 0.875 / 1.0 across three warm runs.
    _14 = [_ok(f"https://{i}.example/") for i in range(14)]
    _2fail = [_fail("https://x.example/"), _fail("https://y.example/")]
    runs = [[*_14], [*_14, *_2fail], [*_14, *_2fail]]
    summary = agg.summarise(runs[-1], [agg.rate(r) for r in runs])

    assert summary["success_rate"] == 0.875
    assert summary["success_rate_observed"]["median"] == 0.875
    assert summary["success_rate_observed"]["max"] == 1.0


def test_repeat_is_order_independent() -> None:
    """Aggregation sorts the rates, so run order cannot change the result."""
    ra = [[_ok("https://a.example/")], [_fail("https://b.example/")]]
    rb = [[_fail("https://b.example/")], [_ok("https://a.example/")]]
    a = agg.summarise(ra[-1], [agg.rate(r) for r in ra])
    b = agg.summarise(rb[-1], [agg.rate(r) for r in rb])

    assert a["success_rate"] == b["success_rate"]


def test_all_unavailable_is_measured_false() -> None:
    """Every source dead is not a measurement, and must not be scored as one."""
    run = [_dead(f"https://{i}.example/") for i in range(16)]

    assert agg.measured(run) is False


def test_one_answer_is_enough_to_measure() -> None:
    """A degraded Pry that still answers is measured — loudly, not as a clean run."""
    run = [_ok("https://a.example/"), _fail("https://b.example/")]

    assert agg.measured(run) is True
    assert agg.rate(run) == 0.5


def test_unmeasurable_is_not_scored_as_a_clean_run() -> None:
    """Every source unreachable is UNMEASURABLE, never a measured clean run.

    The harness used to return 0 on every outcome, so a run where all ten
    sources came back ConnectError was indistinguishable from a total ladder
    regression and a CI gate keying on the exit code passed a broken ladder.
    """
    run = [_dead(f"https://{i}.example/") for i in range(10)]

    assert agg.measured(run) is False
    assert agg.rate(run) == 0.0


def test_the_two_failure_codes_are_different() -> None:
    """They must not collapse into one, or the gate cannot tell 'broken' from
    'unreachable' — which is the whole reason the codes exist."""
    assert cli.EXIT_REGRESSION == 1
    assert cli.EXIT_UNMEASURABLE == 2
    assert cli.EXIT_REGRESSION != cli.EXIT_UNMEASURABLE


def test_compare_flags_a_success_rate_regression(capsys) -> None:
    """Down on success_rate is a regression; flat is not."""
    base = {"success_rate": 1.0, "ok": 10, "p50_ms": 5.0, "p95_ms": 6.0}
    worse = {"success_rate": 0.5, "ok": 5, "p50_ms": 5.0, "p95_ms": 6.0}
    same = {"success_rate": 1.0, "ok": 10, "p50_ms": 5.0, "p95_ms": 6.0}

    assert [k for k, _, _ in cli._compare(base, worse)] == ["success_rate", "ok"]
    assert cli._compare(base, same) == []


def test_compare_inverts_the_direction_for_latency(capsys) -> None:
    """p50 and p95 are latencies: LOWER is better, so a rise is the regression."""
    base = {"success_rate": 1.0, "ok": 10, "p50_ms": 5.0, "p95_ms": 6.0}
    slower = {"success_rate": 1.0, "ok": 10, "p50_ms": 50.0, "p95_ms": 60.0}
    faster = {"success_rate": 1.0, "ok": 10, "p50_ms": 1.0, "p95_ms": 2.0}

    assert {k for k, _, _ in cli._compare(base, slower)} == {"p50_ms", "p95_ms"}
    assert cli._compare(base, faster) == []
