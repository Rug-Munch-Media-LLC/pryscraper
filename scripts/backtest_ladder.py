#!/usr/bin/env python3
"""Backtest the scrape ladder against a labelled source set.

    python3 scripts/backtest_ladder.py --compare
    python3 scripts/backtest_ladder.py --update-baseline

Thin CLI over `ladder_backtest`, which owns the source set, the probe and the
aggregation. This file owns argument parsing, the report, the baseline
comparison, and the EXIT CODE.

Exit codes — the reason this split happened. The harness used to `return 0` on
every outcome, so a run in which all ten sources came back ConnectError (Pry
not deployed, network dead) was indistinguishable from a total ladder
regression: a CI gate keying on the exit code passed a completely broken
ladder, and a broken deployment read as a clean run. Those are different
verdicts, so they get different codes:

    0  measured, no regression        → the gate is free to pass
    1  measured AND regressed         → the ladder got worse
    2  could not measure at all       → no verdict exists; do not call it a pass

Code 2 is not "2 is worse than 1". They are orthogonal: 1 means the ladder was
exercised and failed, 2 means the ladder was never exercised. A caller that
treats any non-zero as "the ladder is broken" has reintroduced exactly the
defect this exit contract removes, so the reason is printed on both paths and
the reason is the thing to read, not the number.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import httpx
from ladder_aggregate import BASELINE, measured, read_baseline, summarise, write_baseline
from ladder_backtest import SOURCES, run_ladder

#: Measured and regressed.
EXIT_REGRESSION = 1
#: Could not measure. Not a verdict about the ladder.
EXIT_UNMEASURABLE = 2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N sources")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--compare", action="store_true", help="diff against the committed baseline")
    ap.add_argument("--no-warmup", action="store_true", help="skip the discarded warm-up pass")
    ap.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="runs to aggregate before summarising (default 3). One run is never a "
        "baseline: on 2026-08-29 three warm runs of an UNCHANGED ladder gave "
        "0.875/0.875/1.0, the 1.0 was committed, and the next run returning 0.75 "
        "was then read as a regression.",
    )
    return ap.parse_args(argv)


def _report(results: list[dict[str, Any]], rates: list[float], summary: dict[str, Any]) -> None:
    print("\n== per source ==")
    for r in results:
        flag = "OK  " if r["result"] == "ok" else "FAIL"
        via = f" via {r['via']}" if r.get("via") else ""
        print(f"  {flag} {r['latency_ms']:>8.1f}ms  {r['url'][:46]:<48}{via}")
        if r["result"] != "ok":
            print(f"       expected={r['expect']}  detail={r.get('detail', '')[:90]}")
    print("\n== summary ==")
    for k, v in summary.items():
        print(f"  {k:14} {v}")


def _compare(base: dict[str, Any], summary: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """Print the diff and return the keys that moved the wrong way.

    A key regresses when it went DOWN relative to the baseline. `p50_ms` and
    `p95_ms` are latencies, so a lower number is the better one and the
    direction is inverted for them.
    """
    print("\n== vs baseline ==")
    band = summary.get("success_rate_observed") or {}
    if band:
        print(
            f"  observed spread baseline={band.get('min')}..{band.get('max')} "
            f"over {band.get('runs')} runs"
        )
    regressions: list[tuple[str, Any, Any]] = []
    for key in ("success_rate", "p50_ms", "p95_ms", "ok"):
        b, n = base.get(key), summary.get(key)
        delta = (
            "n/a"
            if b is None or n is None or isinstance(b, str)
            else round(n - b, 3)
            if isinstance(b, float)
            else n - b
        )
        print(f"  {key:14} baseline={b}  now={n}  delta={delta}")
        if delta == "n/a" or delta == 0:
            continue
        worse = delta < 0 if key in ("success_rate", "ok") else delta > 0
        if worse:
            regressions.append((key, b, n))
    return regressions


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sources = SOURCES[: args.limit] if args.limit else SOURCES

    async with httpx.AsyncClient(timeout=args.timeout + 30) as client:
        results, rates = await run_ladder(
            client,
            sources=sources,
            repeat=args.repeat,
            budget=args.timeout,
            warmup=not args.no_warmup,
        )
    summary = summarise(results, rates)
    print(f"\n== {len(rates)} runs, success_rate per run: {sorted(rates)}")
    print(
        f"== median {summary['success_rate']}  (baseline compares against the MEDIAN, not a single run)"
    )
    _report(results, rates, summary)

    # File I/O is synchronous and this is an async function, so it happens in
    # asyncio.to_thread rather than blocking the event loop (ASYNC240).
    if args.update_baseline:
        await asyncio.to_thread(write_baseline, summary, results)
        print(f"\n  baseline written to {BASELINE}")
        return 0

    if not measured(results):
        # The ladder was never exercised. Say so in terms a CI log can act on,
        # and refuse to let "no data" pass for "no problem".
        unavailable = sum(1 for r in results if r["result"] == "unavailable")
        print(
            f"\n  UNMEASURABLE: 0/{len(results)} sources reached Pry "
            f"({unavailable} unavailable). This is a missing deployment or a dead "
            f"network, NOT a ladder verdict — the chain was never exercised."
        )
        return EXIT_UNMEASURABLE

    if args.compare:
        regressions = _compare(await asyncio.to_thread(read_baseline), summary)
        if regressions:
            for key, b, n in regressions:
                print(f"\n  REGRESSION: {key} baseline={b} now={n}")
            print(f"  ladder REGRESSED against the committed baseline (exit {EXIT_REGRESSION})")
            return EXIT_REGRESSION
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
