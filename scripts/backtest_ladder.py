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

import httpx
from ladder_aggregate import (
    BASELINE,
    measured,
    offline_summary,
    read_baseline,
    read_results,
    summarise,
    write_baseline,
)
from ladder_backtest import SOURCES, run_ladder
from ladder_report import compare, report

# Re-exported under the old private names so the existing tests
# (`cli._compare`, the reporting half) keep importing the one surface.
_report = report
_compare = compare

#: Measured and regressed.
EXIT_REGRESSION = 1


def _covers_current_sources(results: list[dict], want: set[str] | None = None) -> bool:
    """True when the fixture/baseline describes the SAME source set we measure.

    A success-rate diff across different source sets is not a regression, it is
    a different experiment. The committed ``data/ladder_baseline.json`` is a
    one-source placeholder (``a.example``) while ``SOURCES`` defines ten, so
    comparing the two would report a real 9/10 run as a "regression" from a
    fabricated 1.0. Refuse the comparison instead of inventing a verdict.
    """
    have = {r.get("url") for r in results}
    expected = want if want is not None else {s["url"] for s in SOURCES}
    return bool(have) and have == expected


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
        "--offline",
        action="store_true",
        help="replay the committed per-source fixture (data/ladder_baseline.json) "
        "through the same aggregation with no network and no Pry. Deterministic: "
        "the same file yields the same output on every machine. Fail-loud (exit "
        "2) if there is no fixture to replay — never a fabricated pass.",
    )
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


def _offline(argv: list[str] | None) -> int:
    """Replay the committed fixture: no network, no Pry, deterministic.

    The live path measures a DEPLOYED ladder; this path grades the recorded
    per-source results through the identical aggregation. Same file → same
    output on every machine, which is what makes it usable as a reproducible
    check. There is no synthetic jitter: if the fixture is absent the run is
    UNMEASURABLE (exit 2) with a message that names the missing file, because a
    plausible-looking number that no probe produced is exactly the fake result
    this harness must never emit.
    """
    args = _parse_args(argv)
    results = read_results()
    if not results:
        print(
            f"\n  UNMEASURABLE: no committed fixture at {BASELINE} to replay "
            f"offline (or it has no 'results'). Nothing was measured; refusing "
            f"to fabricate a pass. Run the live path once with "
            f"--update-baseline to record one."
        )
        return EXIT_UNMEASURABLE

    if not _covers_current_sources(results):
        print(
            f"\n  UNMEASURABLE: {BASELINE} covers {len({r.get('url') for r in results})} "
            f"source(s) but the harness defines {len(SOURCES)}. Replaying a different "
            f"experiment is not a measurement of this one; refusing to grade it. "
            f"Record a real baseline with --update-baseline."
        )
        return EXIT_UNMEASURABLE

    summary = offline_summary(results, args.repeat)
    rates = [summary["success_rate"]] * summary["success_rate_observed"]["runs"]
    print(f"\n== OFFLINE replay of {BASELINE} (deterministic, no network)")
    print(f"\n== {len(rates)} runs, success_rate per run: {sorted(rates)}")
    print(
        f"== median {summary['success_rate']}  (baseline compares against the MEDIAN, not a single run)"
    )
    _report(results, rates, summary)

    if args.compare:
        regressions = _compare(read_baseline(), summary)
        if regressions:
            for key, b, n in regressions:
                print(f"\n  REGRESSION: {key} baseline={b} now={n}")
            print(f"  ladder REGRESSED against the committed baseline (exit {EXIT_REGRESSION})")
            return EXIT_REGRESSION
    return 0


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.offline:
        return _offline(argv)
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
        base_results = await asyncio.to_thread(read_results)
        if not _covers_current_sources(base_results, {s["url"] for s in sources}):
            print(
                f"\n  UNMEASURABLE: the committed baseline covers "
                f"{len({r.get('url') for r in base_results})} source(s) but this run "
                f"measured {len(sources)}. Different source sets cannot be diffed; "
                f"re-record with --update-baseline."
            )
            return EXIT_UNMEASURABLE
        regressions = _compare(await asyncio.to_thread(read_baseline), summary)
        if regressions:
            for key, b, n in regressions:
                print(f"\n  REGRESSION: {key} baseline={b} now={n}")
            print(f"  ladder REGRESSED against the committed baseline (exit {EXIT_REGRESSION})")
            return EXIT_REGRESSION
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
