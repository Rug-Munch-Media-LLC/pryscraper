#!/usr/bin/env python3
"""The pure half of the scrape-ladder backtest: aggregation and persistence.

No httpx, no network, no event loop. Everything here is a function from a list
of probe results to a number, which is why it is the half worth testing: the
median-of-N is the property that stopped a lucky single run being committed as
a baseline, and it is only testable if it is separable from the wire.

`ladder_backtest` probes; `backtest_ladder` reports and picks an exit code.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

BASELINE = Path("data/ladder_baseline.json")

#: A probe result Pry never answered at all. Scored by NOTHING — see `rate`.
UNAVAILABLE = "unavailable"


def rate(run: list[dict[str, Any]]) -> float:
    """Success rate of ONE run, scoring only sources Pry actually answered.

    `unavailable` is excluded from BOTH numerator and denominator. Pry being
    down is a missing deployment, not a ladder fault, and folding it into the
    denominator is how an unreachable network becomes indistinguishable from a
    total ladder regression. A run where Pry answered nothing scores 0.0 over
    ZERO sources, which is why `measured`, not this function, is what decides
    whether a verdict is possible at all.
    """
    scored = [r for r in run if r["result"] in ("ok", "fail")]
    if not scored:
        return 0.0
    return round(sum(1 for r in scored if r["result"] == "ok") / len(scored), 3)


def measured(results: list[dict[str, Any]]) -> bool:
    """True when Pry answered at least one source, i.e. a verdict is possible.

    This is the single distinction the old exit code was missing. Every source
    `unavailable` means the harness never reached a Pry and the ladder was
    never exercised: there is no measurement, so there is nothing to call a
    regression and nothing to call a pass either.
    """
    return any(r["result"] in ("ok", "fail") for r in results)


def median_rate(rates: list[float]) -> float:
    """The MEDIAN of the per-run rates — the number a baseline must record.

    One run is never a baseline: on 2026-08-29 three warm runs of an UNCHANGED
    ladder gave 0.875 / 0.875 / 1.0, the 1.0 was committed, and the next run
    returning 0.75 was then read as a regression. The median is the reason a
    lucky run stops being load-bearing, so `summary["success_rate"]` is built
    from THIS and never from `rates[-1]`.
    """
    ordered = sorted(rates)
    return ordered[len(ordered) // 2]


def spread(rates: list[float]) -> dict[str, Any]:
    """The min/median/max band the per-run rates occupied.

    Recorded into the baseline so `--compare` has a real tolerance to print and
    a future gate can read the noise band instead of guessing one. Before this
    existed the writer persisted a summary with no spread while the reader's
    spread branch read `summary["success_rate_observed"]`, so that branch was
    dead code and the committed baseline recorded no tolerance at all.
    """
    ordered = sorted(rates)
    return {
        "runs": len(ordered),
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "max": ordered[-1],
    }


def p95(latencies: list[float]) -> float | None:
    """Nearest-rank 95th percentile of the successful latencies.

    The previous inline `sorted(latencies)[int(len*0.95) - 1]` was off by one
    for small n: with n=2 it returned index 0 (the MINIMUM), so `p95_ms` could
    come out BELOW `p50_ms` — a latency that a "95th percentile is worse than
    the median" claim cannot survive. Nearest-rank is `ceil(q*n) - 1`, clamped
    into `[0, n-1]` (the histogram estimator, which is what a p95 of a small
    hand-labelled set should be). Returns None for an empty list so the caller
    records no number rather than a fabricated 0.
    """
    if not latencies:
        return None
    ordered = sorted(latencies)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return round(ordered[idx], 1)


def summarise(results: list[dict[str, Any]], rates: list[float]) -> dict[str, Any]:
    """The summary dict: the MEDIAN rate, latency, tier mix, and the spread."""
    ok = [r for r in results if r["result"] == "ok"]
    latencies = [r["latency_ms"] for r in results if r["result"] == "ok"]
    return {
        "sources": len(results),
        "ok": len(ok),
        "fail": len(results) - len(ok),
        "success_rate": median_rate(rates),
        "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_ms": p95(latencies),
        "by_via": {v: sum(1 for r in ok if r.get("via") == v) for v in {r.get("via") for r in ok}},
        "success_rate_observed": spread(rates),
    }


def write_baseline(
    summary: dict[str, Any], results: list[dict[str, Any]], path: Path = BASELINE
) -> None:
    """Persist summary + per-source detail. The spread travels with the summary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2) + "\n")


def read_baseline(path: Path = BASELINE) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("summary", {})


def read_results(path: Path = BASELINE) -> list[dict[str, Any]]:
    """The per-source detail committed alongside a baseline, or [] if absent.

    This is what makes an OFFLINE run possible: the recorded probe results are
    a real, labelled fixture. Replaying them through the same aggregation gives
    the same numbers on every machine with no network and no Pry, so the
    harness can be exercised in CI without a deployment — and a missing file is
    an empty list, which `measured` then treats as "nothing measured" rather
    than a fabricated pass.
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    results = data.get("results", [])
    return results if isinstance(results, list) else []


def offline_summary(results: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    """Deterministic summary from recorded results — no probe, no network.

    Every replay sees the identical fixture, so every per-run rate is equal and
    the median equals that rate: the output is byte-identical run to run. This
    is deliberately NOT a simulation of probe jitter — inventing per-run
    variance would fabricate the very number the live path exists to measure.
    `repeat` is honoured only to shape the observed-spread block the way a real
    run would (all repeats equal); it never introduces artificial differences.
    """
    run = list(results)
    rates = [rate(run) for _ in range(max(1, repeat))]
    return summarise(run, rates)
