"""Mega search — fan out across every engine, merge by cross-engine consensus.

A single engine is one opinion: it can be rate-limited, captcha'd, or simply
wrong. This module runs the whole engine set *concurrently* - the existing
:mod:`pry.engine.web_search` chain is a sequential fallback and therefore only
ever pays for one engine - then merges the answers.

The ranking signal is agreement. A URL surfaced by several independent engines
is more likely to be relevant than one surfaced by a single engine, so hits are
scored by how many engines found them, weighted by engine reliability, with
per-engine position and query-term overlap as tie-breakers.

This module does not modify the engine layer; it imports and calls it.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from pry.engine import engine_mojeek, engine_qwant, engine_seznam, engine_yahoo, web_search as ws
from pry.engine.url_key import url_key

logger = logging.getLogger(__name__)

ENGINE_WEIGHTS: dict[str, float] = {
    "searxng": 1.30,
    "duckduckgo": 1.15,
    "mojeek": 1.05,
    "seznam": 1.00,
    "yahoo": 0.95,
    "qwant": 0.90,
}
DEFAULT_ENGINES: tuple[str, ...] = tuple(ENGINE_WEIGHTS)

_PER_ENGINE = 12
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref_", "igshid")
_STRIP_HOST_PREFIXES = ("www.", "m.", "amp.")

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
    """Resolve an engine name to its coroutine."""
    source = ENGINE_SOURCES.get(name)
    return getattr(source[0], source[1]) if source else None


def _term_overlap(query: str, *fields: str) -> float:
    """Fraction of meaningful query terms present in the result text."""
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return 0.0
    haystack = " ".join(fields).lower()
    return sum(1 for t in terms if t in haystack) / len(terms)


def _score(key: str, entry: Result, positions: Positions, query: str) -> float:
    """Consensus dominates; weight, position and term overlap only refine it."""
    engines = positions[key]
    weight = sum(ENGINE_WEIGHTS.get(e, 0.8) for e in engines)
    best_position = min(engines.values())
    overlap = _term_overlap(query, str(entry.get("title") or ""), str(entry.get("snippet") or ""))
    return weight + 0.5 / (1 + best_position) + overlap


async def _gather(
    query: str,
    engines: tuple[str, ...],
    resolve: Callable[[str], Any | None] = _engine_func,
) -> dict[str, list[Result]]:
    """Run every available engine concurrently; a failed leg yields an empty list.

    ``resolve`` is the injection seam: tests inject an engine lookup rather
    than patching module state.
    """
    usable = {n: f for n in engines if (f := resolve(n)) is not None}
    if not usable:
        return {}

    async def run(name: str, func: Any) -> tuple[str, list[Result]]:
        try:
            return name, [r for r in await func(query, _PER_ENGINE) or [] if r.get("url")]
        except Exception as exc:  # noqa: BLE001 - one leg must not sink the rest
            logger.debug("mega_search_leg_failed", extra={"engine": name, "error": str(exc)})
            return name, []

    return dict(await asyncio.gather(*(run(n, f) for n, f in usable.items())))


def _collect(grouped: dict[str, list[Result]]) -> tuple[dict[str, Result], Positions]:
    """Dedupe by normalized URL, keeping the richest payload per unique hit."""
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
    """Rank deduplicated hits by cross-engine consensus."""
    merged, positions = _collect(grouped)
    ranked = sorted(
        merged.items(),
        key=lambda kv: (-_score(kv[0], kv[1], positions, query), kv[1]["url"]),
    )
    for key, entry in ranked:
        entry["consensus"] = len(positions[key])
        entry["sources"] = sorted(set(entry["engines"]))
    return [entry for _, entry in ranked]


async def mega_search(
    query: str,
    num_results: int = 10,
    engines: tuple[str, ...] | None = None,
    resolve: Callable[[str], Any | None] | None = None,
) -> dict[str, Any]:
    """Search every configured engine at once and return a consensus ranking.

    Args:
        query: Search terms.
        num_results: How many merged results to return.
        engines: Subset of engines to use; defaults to all of them.

    Returns:
        ``{"results", "total", "query", "engines", "engines_ok",
        "engines_failed"}``. Each result carries ``consensus`` (how many engines
        surfaced it) and ``sources`` (which ones).
    """
    if not query or not query.strip():
        return {}
    chosen = tuple(engines) if engines else DEFAULT_ENGINES
    grouped = await _gather(query.strip(), chosen, resolve or _engine_func)
    results = _merge(grouped, query.strip())
    ok = [name for name, rows in grouped.items() if rows]
    return {
        "results": results[: max(1, num_results)],
        "total": len(results),
        "query": query.strip(),
        "engines": list(chosen),
        "engines_ok": ok,
        "engines_failed": [n for n in chosen if n not in ok],
    }
