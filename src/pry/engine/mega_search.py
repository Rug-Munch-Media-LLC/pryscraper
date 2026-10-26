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
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from pry.engine import engine_mojeek, engine_qwant, engine_seznam, engine_yahoo, web_search as ws
from pry.engine.url_key import url_key

logger = logging.getLogger(__name__)

ENGINE_WEIGHTS: dict[str, float] = {
    "searxng": 1.30, "duckduckgo": 1.15, "mojeek": 1.05,
    "seznam": 1.00, "yahoo": 0.95, "qwant": 0.90,
}
DEFAULT_ENGINES: tuple[str, ...] = tuple(ENGINE_WEIGHTS)

_PER_ENGINE = 12
PER_ENGINE_TIMEOUT = 3.0
# Reserved out of the budget for merge/response assembly, so wall time stays <= 3 s.
_RESPONSE_RESERVE = 0.05
MIN_CONSENSUS = 2
# A leg may block its own thread (playwright, sync HTTP); a dedicated pool keeps
# that away from the event loop so the deadline is always enforceable.
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


def _term_overlap(query: str, *fields: str) -> float:
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return 0.0
    haystack = " ".join(fields).lower()
    return sum(1 for t in terms if t in haystack) / len(terms)


def _score(entry: Result, engines: dict[str, int], query: str) -> float:
    weight = sum(ENGINE_WEIGHTS.get(e, 0.8) for e in engines)
    overlap = _term_overlap(query, str(entry.get("title") or ""), str(entry.get("snippet") or ""))
    return weight + 0.5 / (1 + min(engines.values())) + overlap


def _run_leg(name: str, func: Any, query: str) -> tuple[str, list[Result], int]:
    """Run one engine in its own event loop inside this thread; never raise."""
    started = time.perf_counter()
    try:
        rows = [r for r in asyncio.run(func(query, _PER_ENGINE)) or [] if r.get("url")]
    except Exception as exc:  # noqa: BLE001 - one leg must not sink the rest
        logger.debug("mega_search_leg_failed", extra={"engine": name, "error": str(exc)})
        rows = []
    return name, rows, int((time.perf_counter() - started) * 1000)


def _agreeing(grouped: dict[str, list[Result]]) -> int:
    seen: dict[str, int] = {}
    for rows in grouped.values():
        for row in rows:
            key = url_key(str(row["url"]))
            seen[key] = seen.get(key, 0) + 1
    return sum(1 for count in seen.values() if count >= MIN_CONSENSUS)


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
        return {"grouped": {}, "per_engine_ms": {}, "pending": [], "elapsed_ms": 0, "partial": False}
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
        done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        for future in done:
            name, rows, ms = future.result()
            grouped[name] = rows
            per_engine_ms[name] = ms
        hits = sum(1 for rows in grouped.values() if rows)
        if _agreeing(grouped) >= 1 or hits >= MIN_CONSENSUS:
            break
    outstanding = sorted(futures[f] for f in pending)
    consumed = int((time.perf_counter() - started) * 1000)
    for name in outstanding:
        per_engine_ms[name] = consumed
    return {
        "grouped": grouped, "per_engine_ms": per_engine_ms, "pending": outstanding,
        "elapsed_ms": consumed, "partial": bool(outstanding),
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
            entry = merged.setdefault(key, {"url": row["url"], "title": "", "snippet": "", "engines": []})
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
        key=lambda e: (-_score(e, positions[url_key(str(e["url"]))], query), e["url"]),
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
        "results": results[: max(1, num_results)], "total": len(results), "query": query.strip(),
        "engines": list(chosen), "engines_ok": ok,
        "engines_failed": [n for n in chosen if n not in ok],
        "engines_timeout": fan["pending"], "partial": fan["partial"],
        "elapsed_ms": fan["elapsed_ms"], "per_engine_ms": fan["per_engine_ms"],
    }
