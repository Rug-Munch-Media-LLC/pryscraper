"""Decides WHAT a GDPR Art. 17 erasure removes, and how the outcome is reported.

Personal data is **deleted**; financial records with a legal retention duty are
**pseudonymised** instead, with the legal basis recorded per store. A sweep is
only ``completed`` when EVERY store was readable and reported its outcome with
zero unreadable records; anything else is ``partial``. Zero affected rows is
``no_matching_records`` -- never a completed attestation.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
import logging
from typing import Any

from pry.compliance._deletion_scan import (  # noqa: F401 -- re-exported
    CONSENT_DIR,
    RecordPredicate,
    _purge_consent,
    _purge_matching_json,
    _quality_predicate,
    _record_user_id,
    _session_predicate,
    _structured_hit,
    _word_boundary_match,
)
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

QUALITY_DIR = PRY_DATA_DIR / "quality"
SESSIONS_DIR = PRY_DATA_DIR / "sessions"

MIN_USER_ID_LENGTH = 3

# (store, action, legal basis) for personal-data stores; these rows are deleted.
FS_SCOPE: tuple[tuple[str, str, str], ...] = (
    ("gdpr/consent", "deleted", "Art. 17(1): consent record, no retention duty"),
    ("quality", "deleted", "Art. 17(1): scrape quality history"),
    ("sessions", "deleted", "Art. 17(1): browser session metadata"),
)
DB_DELETE_SCOPE: tuple[tuple[str, str, str], ...] = (
    ("usage", "deleted", "Art. 17(1): API usage rows"),
    ("scrape_jobs", "deleted", "Art. 17(1): job inputs/results"),
)
DB_PSEUDONYMIISE_SCOPE: tuple[tuple[str, str, str], ...] = (
    ("ledger_entries", "pseudonymised", "Art. 17(3)(b): tax/accounting retention"),
    ("x402_payment_records", "pseudonymised", "Art. 17(3)(b): financial record retention"),
    ("x402_settlement_records", "pseudonymised", "Art. 17(3)(b): settlement retention"),
    ("referrals", "pseudonymised", "Art. 17(3)(b): referral revenue accounting"),
    ("hosting_invoices", "pseudonymised", "Art. 17(3)(b): invoice/tax retention"),
)
JSONL_SCOPE: tuple[tuple[str, str, str], ...] = (
    ("x402/jsonl", "deleted", "Art. 17(1): x402 ledger lines keyed by caller"),
)

# The complete, operator-visible coverage list. If a root is missing from this
# tuple the gap is a defect, not a detail.
ERASURE_SCOPE: tuple[str, ...] = tuple(
    entry[0] for entry in FS_SCOPE + DB_DELETE_SCOPE + DB_PSEUDONYMIISE_SCOPE + JSONL_SCOPE
)

BASIS: dict[str, str] = {
    store: basis
    for store, _, basis in (FS_SCOPE + DB_DELETE_SCOPE + DB_PSEUDONYMIISE_SCOPE + JSONL_SCOPE)
}


def _entry(
    store: str,
    action: str,
    affected: int,
    unreadable: int = 0,
    state: str = "ok",
) -> dict[str, Any]:
    """One per-store manifest row, including the recorded legal basis."""
    return {
        "store": store,
        "action": action,
        "basis": BASIS.get(store, "Art. 17(1)"),
        "affected": affected,
        "unreadable": unreadable,
        "state": state,
    }


def _result(
    manifest: list[dict[str, Any]], missing_roots: list[str], user_hash: str
) -> dict[str, Any]:
    """Derive status strictly from the per-store manifest.

    ``completed`` requires every store readable (no ``error``/``missing`` state)
    and zero unreadable records. A single hole downgrades the whole request to
    ``partial``; the manifest says which store failed, so an operator can fix it
    and re-run rather than trusting a boolean.
    """
    affected = sum(entry["affected"] for entry in manifest)
    unreadable = sum(entry["unreadable"] for entry in manifest)
    clean = all(entry["state"] in ("ok", "absent") for entry in manifest)
    if not clean or unreadable:
        status = "partial"
    elif affected:
        status = "completed"
    else:
        status = "no_matching_records"
    result: dict[str, Any] = {
        "success": affected > 0,
        "status": status,
        "deleted_records": affected,
        "pseudonymised_records": sum(
            entry["affected"] for entry in manifest if entry["action"] == "pseudonymised"
        ),
        "unreadable_records": unreadable,
        "scanned_roots": list(ERASURE_SCOPE),
        "missing_roots": missing_roots,
        "stores": manifest,
        "user_hash": user_hash,
    }
    if status == "no_matching_records":
        result["note"] = (
            "No records matched the data subject. Erasure is NOT fulfilled: "
            f"{list(ERASURE_SCOPE)} removed nothing; verify coverage before closing."
        )
    elif status == "partial":
        result["note"] = (
            "Erasure is PARTIAL: at least one store was unreadable or unavailable. "
            "Those stores may still hold the subject's data; re-run and verify."
        )
    return result


def process_deletion(user_id: str) -> dict[str, Any]:
    """Delete personal data and pseudonymise retained financial records.

    Matching is exact on structured ``user_id`` fields and falls back to a
    word-boundary match on unstructured content, so short IDs cannot
    over-delete unrelated records.
    """
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
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
            "scanned_roots": list(ERASURE_SCOPE),
            "missing_roots": list(ERASURE_SCOPE),
            "stores": [],
            "user_hash": user_hash,
        }

    consent = _purge_consent(user_hash)
    quality = _purge_matching_json(QUALITY_DIR, _quality_predicate(user_id))
    sessions = _purge_matching_json(SESSIONS_DIR, _session_predicate(user_id))
    manifest = [
        _entry("gdpr/consent", "deleted", consent[0], consent[1], "ok"),
        _entry("quality", "deleted", quality[0], quality[1], "ok" if quality[2] else "absent"),
        _entry("sessions", "deleted", sessions[0], sessions[1], "ok" if sessions[2] else "absent"),
    ]
    missing = [
        name for name, sweep in (("quality", quality), ("sessions", sessions)) if not sweep[2]
    ]

    # Late import: deletion.py imports this module for the plumbing it builds on,
    # so a top-level import here would be circular.
    from pry.compliance import deletion as plumbing

    manifest.extend(plumbing.sweep_database(user_id))
    manifest.append(plumbing.sweep_x402_jsonl(user_id))

    logger.info(
        "deletion_processed",
        extra={
            "user_hash": user_hash,
            "status": _result(manifest, missing, user_hash)["status"],
            "affected": sum(entry["affected"] for entry in manifest),
        },
    )
    return _result(manifest, missing, user_hash)
