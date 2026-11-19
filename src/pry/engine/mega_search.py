"""Mega search — fan out across every engine, merge by cross-engine consensus.

Engines run concurrently under one hard deadline and the call returns as soon as
two engines agree, so one slow or dead engine cannot hold it. Ranking is
agreement: a URL found by several independent engines outranks a lone hit.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from pry.engine import engine_mojeek, engine_qwant, engine_seznam, engine_yahoo, web_search as ws
from pry.engine.fetch_lanes import lane_table

# Re-exported under the historical private names: callers and tests already use
# `mega_search._term_overlap`, and a rename would be a breaking change for a
# function that did not change, only move.
from pry.engine.mega_scoring import (
    DEFAULT_ENGINES,
    ENGINE_HOSTS,
    MIN_CONSENSUS,
    agreeing,
    score,
)
from pry.engine.url_key import url_key

logger = logging.getLogger(__name__)


# Engine -> host it calls, so the response can name the lane that answered.


_PER_ENGINE = 12
# MEASURED, not guessed (2026-11-18, inside the container, all six engines
# gathered concurrently): searxng 1.4s, duckduckgo 9.2s, seznam 11.9s,
# yahoo 12.5s, mojeek 11.1s, qwant 0.4s.
#
# The previous value was 3.0s, which is below FIVE of the six engines. Every leg
# slower than searxng was killed at the deadline and reported as "failed", so a
# six-engine consensus search silently degenerated into a searxng-only search -
# strictly worse than calling searxng directly. A budget under the engines' real
# latency does not make search faster; it makes it single-sourced.
#
# This is also the pool's hard deadline (_fan_out waits at most this long), so
# it must sit above the slowest observed leg with headroom.
PER_ENGINE_TIMEOUT = 15.0
# Reserved out of the budget for merge/response assembly, so wall time stays
# inside PER_ENGINE_TIMEOUT.
_RESPONSE_RESERVE = 0.05
# A leg may block its own thread (playwright, sync HTTP); a dedicated pool keeps
# that away from the event loop so the deadline is always enforceable.
#
# The pool is module-level and long-lived on purpose (a fresh pool per call
# would recreate 8 threads per search), but it MUST be shut down explicitly:
# non-daemon worker threads keep the interpreter alive after the last test or
# request, which is why the suite appeared to hang at teardown. `close_pool()`
# is called from the module-level `atexit` hook below and is safe to call twice.
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mega-search")

Result = dict[str, Any]
Positions = dict[str, dict[str, int]]

# Engine -> (module, attribute); explicit so a module move fails loudly here.
ENGINE_SOURCES: dict[str, tuple[Any, str]] = {
    "searxng": (ws, "_search_searxng"),
    "duckduckgo": (ws, "_search_ddg"),
    "seznam": (engine_seznam, "search_seznam"),
    "yahoo": (engine_yahoo, "search_yahoo"),
    "qwant": (engine_qwant, "search_qwant"),
    "mojeek": (engine_mojeek, "search_mojeek"),
}


def _engine_func(name: str) -> Any | None:
    source = ENGINE_SOURCES.get(name)
    return getattr(source[0], source[1]) if source else None


def _run_leg(name: str, func: Any, query: str) -> tuple[str, list[Result], int]:
    """Run one engine in its own event loop inside this thread; never raise."""
    started = time.perf_counter()
    try:
        rows = [r for r in asyncio.run(func(query, _PER_ENGINE)) or [] if r.get("url")]
    except Exception as exc:  # noqa: BLE001 - one leg must not sink the rest
        logger.debug("mega_search_leg_failed", extra={"engine": name, "error": str(exc)})
        rows = []
    return name, rows, int((time.perf_counter() - started) * 1000)


async def _fan_out(
    query: str,
    engines: tuple[str, ...],
    resolve: Callable[[str], Any | None] = _engine_func,
    per_engine_timeout: float = PER_ENGINE_TIMEOUT,
) -> dict[str, Any]:
    """Fan out under one hard deadline; stop as soon as two engines agree."""
    started = time.perf_counter()
    usable = {n: f for n in engines if (f := resolve(n)) is not None}
    if not usable:
        return {
            "grouped": {},
            "per_engine_ms": {},
            "pending": [],
            "elapsed_ms": 0,
            "partial": False,
        }
    loop = asyncio.get_running_loop()
    futures = {loop.run_in_executor(_POOL, _run_leg, n, f, query): n for n, f in usable.items()}
    grouped: dict[str, list[Result]] = {}
    per_engine_ms: dict[str, int] = {}
    pending: set[Any] = set(futures)
    deadline = started + per_engine_timeout - _RESPONSE_RESERVE
    while pending:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        done, pending = await asyncio.wait(
            pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
        )
        for future in done:
            name, rows, ms = future.result()
            grouped[name] = rows
            per_engine_ms[name] = ms
        hits = sum(1 for rows in grouped.values() if rows)
        # Exit early only once the AGREEMENT threshold is met, not on two hits.
        # Measured 2026-11-18: this broke at two legs, so searxng (1.4s) plus
        # mojeek (11s) cancelled seznam/yahoo/ddg while they were still working
        # and reported them as "failed". With only two legs surviving, every
        # result carried consensus: 1 -- the cross-engine ranking that is the
        # whole reason to run six engines was inert. Callers wanting single-engine
        # latency should call the searxng lane directly.
        if agreeing(grouped) >= MIN_CONSENSUS and hits >= MIN_CONSENSUS:
            break
    outstanding = sorted(futures[f] for f in pending)
    consumed = int((time.perf_counter() - started) * 1000)
    for name in outstanding:
        per_engine_ms[name] = consumed
    return {
        "grouped": grouped,
        "per_engine_ms": per_engine_ms,
        "pending": outstanding,
        "elapsed_ms": consumed,
        "partial": bool(outstanding),
    }


def _collect(grouped: dict[str, list[Result]]) -> tuple[dict[str, Result], Positions]:
    merged: dict[str, Result] = {}
    positions: Positions = {}
    for engine, rows in grouped.items():
        for index, row in enumerate(rows):
            if not str(row["url"]).startswith(("http://", "https://")):
                continue
            key = url_key(str(row["url"]))
            positions.setdefault(key, {}).setdefault(engine, index)
            entry = merged.setdefault(
                key, {"url": row["url"], "title": "", "snippet": "", "engines": []}
            )
            title, snippet = str(row.get("title") or ""), str(row.get("snippet") or "")
            if len(title) > len(str(entry["title"])):
                entry["title"] = title
            if len(snippet) > len(str(entry["snippet"])):
                entry["snippet"] = snippet
            entry["engines"].append(engine)
    return merged, positions


def _merge(grouped: dict[str, list[Result]], query: str) -> list[Result]:
    merged, positions = _collect(grouped)
    ranked = sorted(
        merged.values(),
        key=lambda e: (-score(e, positions[url_key(str(e["url"]))], query), e["url"]),
    )
    for entry in ranked:
        engines = positions[url_key(str(entry["url"]))]
        entry["consensus"] = len(engines)
        entry["sources"] = sorted(set(entry["engines"]))
    return ranked


async def mega_search(
    query: str,
    num_results: int = 10,
    engines: tuple[str, ...] | None = None,
    resolve: Callable[[str], Any | None] | None = None,
    per_engine_timeout: float = PER_ENGINE_TIMEOUT,
) -> dict[str, Any]:
    """Search every configured engine at once and return a consensus ranking.

    ``engines_timeout`` lists legs still pending at the deadline or dropped once
    consensus was reached; ``partial`` is true when any leg did not contribute.
    """
    if not query or not query.strip():
        return {}
    chosen = tuple(engines) if engines else DEFAULT_ENGINES
    fan = await _fan_out(query.strip(), chosen, resolve or _engine_func, per_engine_timeout)
    grouped = fan["grouped"]
    results = _merge(grouped, query.strip())
    ok = [name for name, rows in grouped.items() if rows]
    return {
        "results": results[: max(1, num_results)],
        "total": len(results),
        "query": query.strip(),
        "engines": list(chosen),
        "engines_ok": ok,
        "engines_failed": [n for n in chosen if n not in ok],
        "engines_timeout": fan["pending"],
        "partial": fan["partial"],
        "elapsed_ms": fan["elapsed_ms"],
        "per_engine_ms": fan["per_engine_ms"],
        "per_engine_lane": lane_table(ENGINE_HOSTS),
    }


def close_pool() -> None:
    """Shut the shared thread pool down so the interpreter can exit.

    ``ThreadPoolExecutor`` workers are non-daemon: an idle pool keeps the
    process alive after the last test or request. That presented as the suite
    "hanging at teardown" rather than failing, because pytest finished every
    test and then waited on 8 parked threads. Idempotent -- ``atexit`` and an
    explicit caller may both run it.
    """
    if not _POOL._shutdown:
        _POOL.shutdown(wait=False, cancel_futures=True)


atexit.register(close_pool)
