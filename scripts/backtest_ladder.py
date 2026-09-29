#!/usr/bin/env python3
"""Backtest the scrape ladder against a labelled source set.

WHY THIS EXISTS. Every change to the tier chain so far has been argued rather
than measured. The timeout fix (30 -> 120) was correct and I could not prove
it: the only evidence was one site that happened to work once. Worse, the
failure signature is intermittent because the late tiers (archive, google_cache)
are rate limited, so "it worked yesterday" and "it works now" are different
claims. This replays a fixed, labelled set through the real chain and reports
success rate and latency PER TIER, so a ladder change is a diff against a
number.

    python3 scripts/backtest_ladder.py --baseline data/ladder_baseline.json
    python3 scripts/backtest_ladder.py --update-baseline

It talks to a RUNNING Pry over HTTP with the owner key, so it measures the
deployed system rather than the source tree. Use --limit to keep a run short;
the full set is deliberately small and public so it is reproducible.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

PRY_URL = os.getenv("PRY_URL", "http://127.0.0.1:8005")
BASELINE = Path("data/ladder_baseline.json")

#: Labelled sources. `expect` is what a HEALTHY chain should achieve, measured
#: with plain curl and a browser User-Agent before this harness existed — not
#: what Pry currently returns. That distinction is the point: a tier that fails
#: to deliver a source curl can read is a tier burning time and money.
SOURCES: list[dict[str, Any]] = [
    {"url": "https://rekt.news/", "expect": "ok", "note": "html, plain"},
    {"url": "https://blog.trailofbits.com/", "expect": "ok", "note": "html, plain"},
    {"url": "https://cointelegraph.com/", "expect": "ok", "note": "large html"},
    {"url": "https://thehackernews.com/", "expect": "ok", "note": "html, plain"},
    {"url": "https://immunefi.com/", "expect": "flaky", "note": "JS-heavy, often archive tier"},
    {"url": "https://www.theblock.co/", "expect": "blocked", "note": "403 to curl too"},
    {"url": "https://slowmist.medium.com/", "expect": "blocked", "note": "403 to curl; RSS is the answer"},
    {"url": "https://blog.soliditylang.com/", "expect": "unreachable", "note": "000, not blocking"},
]


def owner_key() -> str:
    key = os.getenv("PRY_API_KEY", "").strip()
    if key:
        return key
    try:
        out = __import__("subprocess").run(
            ["/usr/bin/docker", "inspect", "pry", "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.stdout.splitlines():
        if line.startswith("PRY_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


async def probe(client: httpx.AsyncClient, src: dict[str, Any], pry_timeout: int) -> dict[str, Any]:
    start = time.monotonic()
    try:
        r = await client.post(
            f"{PRY_URL}/v1/scrape",
            json={"url": src["url"], "format": "markdown", "timeout": pry_timeout},
            headers={"Authorization": f"Bearer {owner_key()}"},
        )
    except (httpx.HTTPError, OSError) as exc:
        # A backtest that dies on one unreachable source is useless; record it
        # and carry on. The other sources still measure the ladder.
        return {**src, "result": "unavailable", "latency_ms": 0, "detail": type(exc).__name__}
    ms = round((time.monotonic() - start) * 1000, 1)
    body: dict[str, Any] = {}
    try:
        body = r.json()
    except ValueError:
        return {**src, "result": "unavailable", "latency_ms": ms, "detail": "non-json"}
    if r.status_code == 200 and (body.get("data") or {}).get("markdown"):
        meta = (body.get("data") or {}).get("metadata") or {}
        return {**src, "result": "ok", "latency_ms": ms, "via": meta.get("method", "?")}
    detail = str(body.get("detail", ""))[:120]
    return {**src, "result": "fail", "latency_ms": ms, "detail": detail}


def _write_baseline(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps({"summary": summary, "results": results}, indent=2) + "\n")


def _read_baseline() -> dict[str, Any]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text()).get("summary", {})


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N sources")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--compare", action="store_true", help="diff against the committed baseline")
    args = ap.parse_args()

    sources = SOURCES[: args.limit] if args.limit else SOURCES
    async with httpx.AsyncClient(timeout=args.timeout + 30) as client:
        results = [await probe(client, s, args.timeout) for s in sources]

    ok = [r for r in results if r["result"] == "ok"]
    latencies = [r["latency_ms"] for r in results if r["result"] == "ok"]
    summary = {
        "sources": len(results),
        "ok": len(ok),
        "fail": len(results) - len(ok),
        "success_rate": round(len(ok) / len(results), 3) if results else 0.0,
        "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 1) if latencies else None,
        "by_via": {v: sum(1 for r in ok if r.get("via") == v) for v in {r.get("via") for r in ok}},
    }
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

    # File I/O is synchronous and this is an async function, so it happens in
    # asyncio.to_thread rather than blocking the event loop (ASYNC240).
    if args.update_baseline:
        await asyncio.to_thread(_write_baseline, summary, results)
        print(f"\n  baseline written to {BASELINE}")
        return 0
    if args.compare:
        base = await asyncio.to_thread(_read_baseline)
        print("\n== vs baseline ==")
        for key in ("success_rate", "p50_ms", "p95_ms", "ok"):
            b, n = base.get(key), summary.get(key)
            delta = "n/a" if b is None or n is None or isinstance(b, str) else round(n - b, 3) if isinstance(b, float) else n - b
            print(f"  {key:14} baseline={b}  now={n}  delta={delta}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
