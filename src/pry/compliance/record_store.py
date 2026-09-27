"""Reading GDPR record files without ever reporting unreadable as absent.

A consent or audit record that exists but cannot be parsed is **not** the same
as one that was never written. Collapsing the two is how "the store is
corrupted" turns into "this user refused consent" or "nothing to audit" — and
both of those are the kind of answer a regulator reads.

Every read here therefore reports which files it could not parse, so the
caller can answer UNKNOWN rather than guessing.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

# A record that parses as JSON but is structurally wrong is just as unreadable
# as one that is truncated. KeyError/TypeError/ValueError cover the shape.
RECORD_ERRORS = (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError)


class RecordRead:
    """One pass over a record directory, with what it could not read kept."""

    def __init__(self) -> None:
        self.unreadable: list[str] = []

    def count(self) -> int:
        return len(self.unreadable)

    def note(self) -> str:
        return (
            f"{self.count()} record(s) were unreadable — treat this state as UNKNOWN, not as absent"
        )


def load(path: Path) -> dict[str, Any] | None:
    """Read one JSON record, or ``None`` if it cannot be read.

    ``None`` means "unreadable" — never "absent". The caller decides what an
    unreadable record means for its own contract.
    """
    try:
        return json.loads(path.read_text())
    except RECORD_ERRORS:
        return None


def newest_first(paths: list[Path]) -> list[Path]:
    """Order paths by mtime descending; an unreadable stat keeps it last."""
    return sorted(paths, key=lambda p: _mtime(p), reverse=True)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find(
    paths: list[Path], predicate: Callable[[dict[str, Any]], bool]
) -> tuple[dict[str, Any] | None, RecordRead]:
    """First record matching ``predicate``, newest first, plus what was unreadable.

    Scanning stops at the first match, so records after it are not examined
    and cannot be counted as unreadable. That is intentional: the caller wants
    the current state, not an audit of the whole directory.
    """
    read = RecordRead()
    for path in newest_first(paths):
        record = load(path)
        if record is None:
            read.unreadable.append(path.name)
            continue
        if predicate(record):
            return record, read
    return None, read


def scan(paths: list[Path]) -> tuple[list[dict[str, Any]], RecordRead]:
    """Every readable record, plus the names of the ones that could not be read."""
    read = RecordRead()
    records: list[dict[str, Any]] = []
    for path in paths:
        record = load(path)
        if record is None:
            read.unreadable.append(path.name)
        else:
            records.append(record)
    return records, read


def iter_readable(paths: list[Path]) -> Iterator[dict[str, Any]]:
    """Yield readable records only. Prefer :func:`scan` when you must report."""
    for path in paths:
        record = load(path)
        if record is not None:
            yield record


__all__ = [
    "RECORD_ERRORS",
    "RecordRead",
    "find",
    "iter_readable",
    "load",
    "newest_first",
    "scan",
]
