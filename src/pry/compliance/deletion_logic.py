"""The deletion logic behind GDPR Art. 17, split out of :mod:`pry.compliance.deletion`.

``deletion`` keeps the request/response plumbing (record the request, execute it,
report the outcome); this module is the part that decides WHAT a deletion request
actually removes. The split is behavioural: every function here is re-exported
from ``deletion``, so ``pry.compliance.gdpr`` and the GDPR router are unchanged.

The core rule, and the reason ``process_deletion`` is careful about how it
matches: matching is exact on structured ``user_id`` fields and falls back to a
word-boundary match on unstructured content, so a short ID like "a" cannot
over-delete unrelated records.

Two invariants this module exists to hold:

1. **Every data root is derived from ``PRY_DATA_DIR``.** In production
   ``PRY_DATA_DIR`` and ``HOME`` are different trees (``/app/pry-data`` vs
   ``/app/pry-data/home``), so a home-relative path silently points at a
   directory that holds nothing. Scanning an empty tree and reporting success is
   a false compliance attestation, which is worse than an honest failure.
2. **Zero deletions is not success.** ``process_deletion`` returns
   ``success=False`` with ``status="no_matching_records"`` when it removed
   nothing, so the caller cannot stamp the request ``completed``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
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

# Derived from PRY_DATA_DIR rather than imported from ``deletion``, which
# imports this module -- a direct import would be circular. Identical path.
CONSENT_DIR = PRY_DATA_DIR / "gdpr" / "consent"

# Same reasoning as CONSENT_DIR, and the SAME directories their writers use:
# pry.engine.quality.QUALITY_DIR and pry.engine.sessions.SESSIONS_DIR. These
# must not be spelled ``~/.pry/...`` -- see invariant (1) in the module
# docstring for what that costs.
QUALITY_DIR = PRY_DATA_DIR / "quality"
SESSIONS_DIR = PRY_DATA_DIR / "sessions"

# Every data root process_deletion sweeps, in the order it sweeps them. Echoed
# back in the result so an operator can verify COVERAGE instead of trusting a
# boolean. If a root is added here it is visible; if one is missing, the gap is
# visible in this list.
ERASURE_SCOPE: tuple[str, ...] = ("gdpr/consent", "quality", "sessions")

# Minimum length for a user_id to be eligible for deletion. Shorter identifiers
# (e.g. a single character like "a") would match many unrelated records when
# searching unstructured content, risking over-deletion of other users' data.
MIN_USER_ID_LENGTH = 3

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


def _result(
    *, deleted: int, unreadable: int, missing_roots: list[str], user_hash: str
) -> dict[str, Any]:
    """Build the process_deletion response from the sweep totals.

    ``success`` is True only when records were actually removed. Zero removals
    is reported as an explicit failure with ``status="no_matching_records"`` --
    a distinct, greppable, operator-visible state -- because the difference
    between "the subject had no records" and "we scanned the wrong tree" is
    exactly what the old silent-success erased.
    """
    status = "completed" if deleted > 0 else "no_matching_records"
    result: dict[str, Any] = {
        "success": deleted > 0,
        "status": status,
        "deleted_records": deleted,
        "unreadable_records": unreadable,
        "scanned_roots": list(ERASURE_SCOPE),
        "missing_roots": missing_roots,
        "user_hash": user_hash,
    }
    if deleted == 0:
        result["note"] = (
            "No records matched the data subject. Erasure is NOT fulfilled: the sweep "
            f"covered {list(ERASURE_SCOPE)} and removed nothing, so either no data is "
            "held or the data lives outside these roots. Verify before closing."
        )
    elif unreadable:
        result["note"] = (
            f"{unreadable} record(s) in scope could not be read or removed; those may "
            "still hold the data subject's data"
        )
    return result


def process_deletion(user_id: str) -> dict[str, Any]:
    """Process data deletion for a user (GDPR Art. 17).

    Removes the subject's data across every root named in ``ERASURE_SCOPE``:
    consent records, quality history, browser sessions.

    Matching is exact on structured ``user_id`` fields and falls back to a
    word-boundary match on unstructured content, so short IDs cannot
    over-delete unrelated records.

    Returns ``success=False`` with ``status="no_matching_records"`` when nothing
    was removed. The caller must not treat that as a fulfilled erasure.
    """
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]

    # Guard against overly broad matches from very short identifiers.
    if len(user_id) < MIN_USER_ID_LENGTH:
        logger.warning(
            "deletion_rejected_short_user_id",
            extra={"user_hash": user_hash, "user_id_length": len(user_id)},
        )
        return {
            "success": False,
            "status": "rejected",
            "error": f"user_id must be at least {MIN_USER_ID_LENGTH} characters",
            "deleted_records": 0,
            "unreadable_records": 0,
            "scanned_roots": list(ERASURE_SCOPE),
            "missing_roots": list(ERASURE_SCOPE),
            "user_hash": user_hash,
        }

    consent, quality, sessions = (
        _purge_consent(user_hash),
        _purge_matching_json(QUALITY_DIR, _quality_predicate(user_id)),
        _purge_matching_json(SESSIONS_DIR, _session_predicate(user_id)),
    )
    deleted = sum(removed for removed, _, _ in (consent, quality, sessions))
    unreadable = sum(failed for _, failed, _ in (consent, quality, sessions))
    missing = [
        name for name, sweep in (("quality", quality), ("sessions", sessions)) if not sweep[2]
    ]

    logger.info(
        "deletion_processed",
        extra={
            "user_hash": user_hash,
            "deleted_records": deleted,
            "unreadable_records": unreadable,
        },
    )
    return _result(
        deleted=deleted, unreadable=unreadable, missing_roots=missing, user_hash=user_hash
    )
