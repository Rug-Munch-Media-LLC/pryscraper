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
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 1)
        if latencies
        else None,
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
