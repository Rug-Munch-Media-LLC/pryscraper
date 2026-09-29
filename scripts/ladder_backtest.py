#!/usr/bin/env python3
"""The network half of the scrape-ladder backtest: source set, probe, warm-up.

WHY THIS EXISTS. Every change to the tier chain so far has been argued rather
than measured. The timeout fix (30 -> 120) was correct and I could not prove
it: the only evidence was one site that happened to work once. Worse, the
failure signature is intermittent because the late tiers (archive, google_cache)
are rate limited, so "it worked yesterday" and "it works now" are different
claims. This replays a fixed, labelled set through the real chain and reports
success rate and latency PER TIER, so a ladder change is a diff against a
number.

It talks to a RUNNING Pry over HTTP with the owner key, so it measures the
deployed system rather than the source tree.

Two modules, three files, one behaviour. `ladder_backtest` is this file: the
half that touches the wire. `ladder_aggregate` is the pure half (rate, median,
spread, summarise, baseline I/O) and is where the median-of-N test lives,
because a property that cannot be separated from httpx cannot be tested without
a network. `backtest_ladder` is the thin CLI that reports and picks an exit
code. The split is line-budget driven — every file is under the 200-line cap —
and it was done by MOVING code, never by dropping it.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import httpx

PRY_URL = os.getenv("PRY_URL", "http://127.0.0.1:8005")

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
    {
        "url": "https://slowmist.medium.com/",
        "expect": "blocked",
        "note": "403 to curl; RSS is the answer",
    },
    # 2026-08-29: blog.soliditylang.com REMOVED, replaced by three sources that
    # are actually reachable and that exercise the browser tier.
    #
    # Why it was removed rather than fixed: the host answers the TLS ClientHello
    # with `tlsv1 unrecognized name` and presents NO certificate. openssl
    # tolerates that and prints "Verify return code: 0"; Chrome does not, so the
    # browser FlareSolverr drives fails with net::ERR_SSL_UNRECOGNIZED_NAME_ALERT
    # and the tier intermittently returns 0 bytes. Both A records (13.248.169.48,
    # 76.223.154.146) behave identically, so it is a hostname/cert
    # misconfiguration at the site, not one bad backend in a pool. No ladder
    # ordering, proxy, tier or timeout can make a hostname with no certificate
    # load in a browser, and a source that is unreachable for reasons outside our
    # control is a bad test fixture: it pins the baseline at 7/8 forever and makes
    # every future run look like a regression.
    {"url": "https://bitcoin.org/en/", "expect": "ok", "note": "browser tier, small"},
    {"url": "https://geth.ethereum.org/", "expect": "ok", "note": "browser tier"},
    {"url": "https://base.org/", "expect": "ok", "note": "browser tier, JS-rendered"},
]

#: Sources used to warm a specific tier, because the tier pool is shared and
#: cold-starting it is what produces the misleading latency.
WARMUP_TIERS = ("https://blog.soliditylang.com/",)


def owner_key() -> str:
    key = os.getenv("PRY_API_KEY", "").strip()
    if key:
        return key
    try:
        out = subprocess.run(
            [
                "/usr/bin/docker",
                "inspect",
                "pry",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
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
        # and carry on. The other sources still measure the ladder. Note this
        # is NOT the same as a fail: an `unavailable` source is one Pry never
        # answered, so it says nothing about the ladder. `rate` ignores both.
        return {**src, "result": UNAVAILABLE, "latency_ms": 0, "detail": type(exc).__name__}
    ms = round((time.monotonic() - start) * 1000, 1)
    body: dict[str, Any] = {}
    try:
        body = r.json()
    except ValueError:
        return {**src, "result": UNAVAILABLE, "latency_ms": ms, "detail": "non-json"}
    if r.status_code == 200 and (body.get("data") or {}).get("markdown"):
        meta = (body.get("data") or {}).get("metadata") or {}
        return {**src, "result": "ok", "latency_ms": ms, "via": meta.get("method", "?")}
    detail = str(body.get("detail", ""))[:120]
    return {**src, "result": "fail", "latency_ms": ms, "detail": detail}


async def warm_browser_tier(client: httpx.AsyncClient, url: str, budget: int) -> None:
    """Force one scrape through the browser tier so its pool is hot.

    Best-effort: a warm-up failure is not a test failure, the source may simply
    be unreachable. The point is only that the pool starts before measuring.
    """
    try:
        # `budget` is Pry's own timeout field, NOT an httpx socket wait;
        # named so the two cannot be confused (ASYNC109).
        await probe(client, {"url": url, "expect": "ok", "note": "warmup"}, budget)
    except Exception:  # noqa: BLE001 - warm-up must never break a measurement
        return


async def warm(client: httpx.AsyncClient, sources: list[dict[str, Any]], budget: int) -> None:
    """One discarded pass that brings both warm pools up before measuring.

    Measured across 3 runs 2026-08-29: p50 853.9 / 3.8 / 4.0, p95 1005.8 / 9.2 /
    4.3. The first run after a container rebuild is ~200x slower on p50, and it
    was that cold number that got committed as a baseline and read as a latency
    regression. The success rate and tier selection were identical across all
    three runs (0.875, same by_via) — only the timings moved. So a cold baseline
    is not merely noisy, it is misleading in a specific direction.

    Warm the tier the SLOW sources need, not the one the first source happens to
    use. Warming sources[0] (rekt.news, served by `direct` in ~3ms) left the
    flaresolverr BROWSER POOL cold, so the first run that needed it still paid
    the full start: the baseline written by --update-baseline came out p50
    802ms even with the warm-up in place. Hence the explicit browser tier.
    """
    if not sources:
        return
    await probe(client, sources[0], budget)
    for tier in WARMUP_TIERS:
        await warm_browser_tier(client, tier, budget)


async def run_ladder(
    client: httpx.AsyncClient,
    *,
    sources: list[dict[str, Any]],
    repeat: int,
    budget: int,
    warmup: bool = True,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Warm, then `repeat` measured passes over `sources`.

    Returns the LAST run (the per-source detail that gets reported) and the
    per-run success rates, in run order. The warm-up runs twice over: once as a
    standalone discarded pass, and again at the head of every measured run, so a
    pass that follows a slow one does not start on a re-cooled pool. That shape
    is preserved from the pre-split script exactly.
    """
    if warmup:
        await warm(client, sources, budget)
    runs: list[list[dict[str, Any]]] = []
    for _ in range(max(1, repeat)):
        if warmup:
            await warm(client, sources, budget)
        runs.append([await probe(client, src, budget) for src in sources])
    return runs[-1], [rate(run) for run in runs]


# The aggregation half lives in `ladder_aggregate` (no network, no event loop).
# Re-exported here so the CLI takes the whole measurement surface from one
# import and the old `ladder_backtest.rate` / `.summarise` names keep resolving.
from ladder_aggregate import (  # noqa: E402
    UNAVAILABLE,
    rate,
)
