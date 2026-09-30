"""Record matching and file purging for GDPR erasure, split out of ``deletion_logic``.

``deletion_logic`` owns WHAT a deletion request means and how the outcome is
reported; this module owns HOW a record is judged to belong to the data subject
and how it is removed from a root. The boundary is deliberate: everything here
is a pure predicate or a filesystem sweep, so it is the part that can be reasoned
about (and regression-tested) without touching the response contract.

The two invariants carried down from :mod:`pry.compliance.deletion_logic`:

1. **Every data root is derived from ``PRY_DATA_DIR``**, never ``~/.pry``. In
   production those are different trees, so a home-relative path points at a
   directory that holds nothing and the sweep silently finds zero records.
2. **A record that cannot be read is never treated as "not this user's".** It is
   counted as a hole in the erasure, not as a clean sweep -- we cannot prove it
   does not hold the subject's data.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pry.compliance import record_store
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

# Single definition, re-exported by deletion_logic: the consent writer in
# pry.compliance.deletion writes under GDPR_DIR / "consent", which is this path.
CONSENT_DIR = PRY_DATA_DIR / "gdpr" / "consent"

# Record predicates take a decoded record and answer "is this the data subject?".
RecordPredicate = Callable[[dict[str, Any]], bool]


def _word_boundary_match(user_id: str, content: str) -> bool:
    """Return True if ``user_id`` appears as a whole word in ``content``.

    Uses a word-boundary regex so a short ID like "a" cannot match inside
    unrelated tokens (e.g. "data", "email"). Case-insensitive.
    """
    return re.search(r"\b" + re.escape(user_id) + r"\b", content, re.IGNORECASE) is not None


def _record_user_id(record: dict[str, Any]) -> str | None:
    """Extract a structured user identifier from a JSON record, if present.

    Checks common field names for a string user identifier. Returns None when
    the record carries no structured user field.
    """
    for key in ("user_id", "userId", "user", "email"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _structured_hit(record: dict[str, Any], user_id: str) -> bool:
    """True when a structured ``user_id`` field is an exact (case-insensitive) match."""
    found = _record_user_id(record)
    return found is not None and found.lower() == user_id.lower()


def _quality_predicate(user_id: str) -> RecordPredicate:
    """Predicate for ``quality/*.json``: structured user field, else word-boundary on the URL."""
    lower = user_id.lower()

    def matches(data: dict[str, Any]) -> bool:
        inner = data.get("data")
        if _structured_hit(data, user_id) or (
            isinstance(inner, dict) and _structured_hit(inner, user_id)
        ):
            return True
        url = data.get("url", "")
        return isinstance(url, str) and bool(url) and _word_boundary_match(lower, url)

    return matches


def _session_predicate(user_id: str) -> RecordPredicate:
    """Predicate for ``sessions/*.json``: structured user field, else word-boundary on metadata."""
    lower = user_id.lower()

    def matches(data: dict[str, Any]) -> bool:
        meta = data.get("metadata") or {}
        meta = meta if isinstance(meta, dict) else {}
        if _structured_hit(meta, user_id) or _structured_hit(data, user_id):
            return True
        return _word_boundary_match(lower, json.dumps(meta))

    return matches


def _purge_matching_json(directory: Path, matches: RecordPredicate) -> tuple[int, int, bool]:
    """Delete every readable ``*.json`` in ``directory`` that ``matches`` selects.

    Returns ``(deleted, unreadable, present)``. A record that cannot be read is
    counted, never treated as "not this user's": we cannot prove it does not
    hold the data subject's data, so it is a hole in the erasure, not a clean
    sweep. ``present`` is False when the root does not exist at all, which the
    caller reports as a coverage gap rather than as "nothing to delete".
    """
    deleted = 0
    unreadable = 0
    if not directory.is_dir():
        return deleted, unreadable, False
    for path in sorted(directory.glob("*.json")):
        data = record_store.load(path)
        if data is None:
            unreadable += 1
            logger.warning("gdpr_deletion_scan_failed", extra={"root": directory.name})
            continue
        if not matches(data):
            continue
        try:
            path.unlink()
        except OSError as exc:
            unreadable += 1
            logger.error(
                "gdpr_record_delete_failed",
                extra={"root": directory.name, "error": str(exc)[:160]},
            )
            continue
        deleted += 1
    return deleted, unreadable, True


def _purge_consent(user_hash: str) -> tuple[int, int, bool]:
    """Delete this subject's consent records, keyed by the hashed filename prefix."""
    deleted = 0
    failed = 0
    for path in sorted(CONSENT_DIR.glob(f"{user_hash}_*.json")):
        try:
            path.unlink()
        except OSError as exc:
            failed += 1
            logger.error(
                "gdpr_consent_record_delete_failed",
                extra={"root": CONSENT_DIR.name, "error": str(exc)[:160]},
            )
            continue
        deleted += 1
    return deleted, failed, True
