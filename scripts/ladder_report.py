#!/usr/bin/env python3
"""The presentation half of the scrape-ladder backtest: print and diff.

Split out of `backtest_ladder` to keep that CLI under the 200-line cap. This is
pure formatting over the summary/result dicts the aggregation produces — no
network, no event loop, no baseline I/O — so it is testable on its own and the
CLI keeps only argument parsing and the exit-code decision.

`_compare` owns one subtlety worth stating: `p50_ms` and `p95_ms` are
latencies, so LOWER is better and the regression direction is INVERTED for
them. Everything else (success_rate, ok) regresses when it goes DOWN.
"""

from __future__ import annotations

from typing import Any


def report(results: list[dict[str, Any]], rates: list[float], summary: dict[str, Any]) -> None:
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


def compare(base: dict[str, Any], summary: dict[str, Any]) -> list[tuple[str, Any, Any]]:
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
