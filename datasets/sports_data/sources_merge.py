"""Cross-source odds merge for the sports odds fetchers.

Dedupes records across sources by (event, market, book), prefers sharp
books (Pinnacle) on conflict, then source priority, then recency, and
keeps the winning record's ``source`` tag.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datetime import datetime
from typing import Any

from datasets.sports_data.sources_common import same_event

# ── Cross-source merge ──────────────────────────────────────────────────
_SHARP_BOOKS = frozenset({"pinnacle"})


def _source_rank(record: dict[str, Any]) -> int:
    """Priority index of a record's source (lower = preferred)."""
    from datasets.sports_data import sources as _base

    source = str(record.get("source") or "").strip().lower()
    try:
        return _base.SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(_base.SOURCE_PRIORITY)


def _ts_float(value: Any) -> float:
    """ISO timestamp -> epoch seconds; missing/unparseable -> -inf."""
    if not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _priority_key(record: dict[str, Any], index: int) -> tuple[Any, ...]:
    """Sort key: sharpest book first, then source rank, then newer update."""
    book = str(record.get("book") or "").strip().lower()
    sharp = 0 if book in _SHARP_BOOKS else 1
    return (sharp, _source_rank(record), -_ts_float(record.get("last_update")), index)


def _conflicts(record_a: dict[str, Any], record_b: dict[str, Any]) -> bool:
    """True when two records describe the same (event, market, book)."""
    if str(record_a.get("market") or "") != str(record_b.get("market") or ""):
        return False
    if str(record_a.get("book") or "") != str(record_b.get("book") or ""):
        return False
    return same_event(record_a, record_b)


def merge_odds(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe odds records across sources.

    Records are grouped by (event, market, book); on a conflict (the same
    event+market+book reported by two sources with different lines) the
    winner is:

    1. the sharpest book (Pinnacle beats everyone),
    2. the highest-confidence source (:data:`SOURCE_PRIORITY` order),
    3. the most recent ``last_update``,
    4. the earliest position in the input.

    Non-conflicting records (different books, different events) are all
    kept, and output preserves the input order. Each surviving record keeps
    its original ``source`` tag.
    """
    keyed: list[tuple[int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        keyed.append((index, record))
    ordered = sorted(keyed, key=lambda pair: _priority_key(pair[1], pair[0]))
    accepted: list[tuple[int, dict[str, Any]]] = []
    for index, record in ordered:
        if any(_conflicts(record, acc) for _, acc in accepted):
            continue
        accepted.append((index, record))
    accepted.sort(key=lambda pair: pair[0])
    return [record for _, record in accepted]
