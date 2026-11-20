"""Mega search scoring — how strongly one engine's hit counts.

Separated from the fan-out and the merge because these are pure functions over
rows: they have no I/O, no deadline, and no knowledge of which engines are
online. Keeping them here means the ranking can be tested without launching six
browsers, and the fan-out module stays about concurrency only.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from typing import Any

from pry.engine.url_key import url_key

Result = dict[str, Any]

#: Trust weight per engine. A hit found by a high-weight engine outranks the same
#: hit found only by a low-weight one when agreement is otherwise equal.
ENGINE_WEIGHTS: dict[str, float] = {
    "searxng": 1.30,
    "duckduckgo": 1.15,
    "mojeek": 1.05,
    "seznam": 1.00,
    "yahoo": 0.95,
    "qwant": 0.90,
}

#: Every engine this lane asks, in weight order.
DEFAULT_ENGINES: tuple[str, ...] = tuple(ENGINE_WEIGHTS)

#: How many engines must return the SAME url for it to count as agreement.
#: This is the threshold the fan-out waits for before it stops early.
MIN_CONSENSUS = 2

#: Host each engine calls, so a response can name the lane that answered.
ENGINE_HOSTS: dict[str, str] = {
    "searxng": "localhost",
    "duckduckgo": "html.duckduckgo.com",
    "qwant": "api.qwant.com",
}


def term_overlap(query: str, *fields: str) -> float:
    """Fraction of the query's meaningful terms present in ``fields``.

    Terms of three characters or fewer are ignored: they match almost any English
    text and would reward unrelated pages.
    """
    terms = [t for t in query.lower().split() if len(t) > 2]
    if not terms:
        return 0.0
    haystack = " ".join(fields).lower()
    return sum(1 for t in terms if t in haystack) / len(terms)


def score(entry: Result, engines: dict[str, int], query: str) -> float:
    """Rank one merged result.

    Three signals, summed:
      * the summed weight of every engine that returned it — the consensus value
        that makes this lane worth running;
      * a small bonus for appearing high in a result list;
      * query-term overlap with the title and snippet, which keeps a
        high-consensus but off-topic hit from outranking a precise one.

    Args:
        entry: Merged result carrying ``engines`` (name -> best position).
        engines: Per-engine best positions for this URL.
        query: The original query.

    Returns:
        A comparable float; higher is better.
    """
    weight = sum(ENGINE_WEIGHTS.get(e, 0.8) for e in engines)
    overlap = term_overlap(query, str(entry.get("title") or ""), str(entry.get("snippet") or ""))
    return weight + 0.5 / (1 + min(engines.values())) + overlap


def _agreeing(grouped: dict[str, list[Result]]) -> int:
    """How many distinct URLs were returned by MIN_CONSENSUS or more engines.

    This is the number the fan-out waits for. It is deliberately a count of
    AGREED URLs rather than of engines that answered: six engines returning six
    disjoint lists agree on nothing, and stopping there would truncate the vote
    that this lane exists to take.
    """
    seen: dict[str, int] = {}
    for rows in grouped.values():
        for row in rows:
            key = url_key(str(row["url"]))
            seen[key] = seen.get(key, 0) + 1
    return sum(1 for count in seen.values() if count >= MIN_CONSENSUS)


def agreeing(grouped: dict[str, list[Result]]) -> int:
    """Public wrapper for :func:`_agreeing` (fan-out uses this)."""
    return _agreeing(grouped)


__all__ = [
    "DEFAULT_ENGINES",
    "ENGINE_HOSTS",
    "ENGINE_WEIGHTS",
    "MIN_CONSENSUS",
    "Result",
    "agreeing",
    "score",
    "term_overlap",
]
