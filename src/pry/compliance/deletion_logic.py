"""The deletion logic behind GDPR Art. 17, split out of :mod:`pry.compliance.deletion`.

``deletion`` keeps the request/response plumbing (record the request, execute it,
report the outcome); this module is the part that decides WHAT a deletion request
actually removes. The split is behavioural: every function here is re-exported
from ``deletion``, so ``pry.compliance.gdpr`` and the GDPR router are unchanged.

The core rule, and the reason ``process_deletion`` is careful about how it
matches: matching is exact on structured ``user_id`` fields and falls back to a
word-boundary match on unstructured content, so a short ID like "a" cannot
over-delete unrelated records.
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
import os
import re
from pathlib import Path
from typing import Any

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

# Derived from PRY_DATA_DIR rather than imported from ``deletion``, which
# imports this module -- a direct import would be circular. Identical path.
CONSENT_DIR = PRY_DATA_DIR / "gdpr" / "consent"


# Minimum length for a user_id to be eligible for deletion. Shorter identifiers
# (e.g. a single character like "a") would match many unrelated records when
# searching unstructured content, risking over-deletion of other users' data.
MIN_USER_ID_LENGTH = 3


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


def process_deletion(user_id: str) -> dict[str, Any]:
    """Process data deletion for a user (GDPR Art. 17).

    This finds and removes all data associated with the user across
    Pry's storage: consent records, quality history, sessions, etc.

    Matching is exact on structured ``user_id`` fields and falls back to a
    word-boundary match on unstructured content, so short IDs cannot
    over-delete unrelated records.
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
            "error": f"user_id must be at least {MIN_USER_ID_LENGTH} characters",
            "deleted_records": 0,
            "user_hash": user_hash,
        }

    deleted_records = 0

    # Delete consent records
    for path in CONSENT_DIR.glob(f"{user_hash}_*.json"):
        try:
            path.unlink()
            deleted_records += 1
        except OSError as e:
            # Erasure MUST be complete for compliance; surface partial failures.
            logger.error(
                "gdpr_consent_record_delete_failed",
                extra={"path": str(path), "error": str(e)[:160]},
            )

    # Delete from quality history (if email in URLs)
    quality_dir = Path(os.path.expanduser("~/.pry/quality"))
    if quality_dir.exists():
        for path in quality_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                # Exact match on a structured user_id field if present.
                record_user = _record_user_id(data) or _record_user_id(data.get("data") or {})
                if record_user is not None and record_user.lower() == user_id.lower():
                    path.unlink()
                    deleted_records += 1
                    continue
                # Fall back to word-boundary match on the URL (unstructured).
                url = data.get("url", "")
                if url and _word_boundary_match(user_id, url):
                    path.unlink()
                    deleted_records += 1
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("gdpr_deletion_scan_failed", extra={"error": str(e)[:160]})

    # Delete sessions associated with this user
    sessions_dir = Path(os.path.expanduser("~/.pry/sessions"))
    if sessions_dir.exists():
        for path in sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                meta = data.get("metadata", {}) or {}
                # Exact match on a structured user_id field if present.
                record_user = _record_user_id(meta) or _record_user_id(data)
                if record_user is not None and record_user.lower() == user_id.lower():
                    path.unlink()
                    deleted_records += 1
                    continue
                # Fall back to word-boundary match on the metadata (unstructured).
                if _word_boundary_match(user_id, json.dumps(meta)):
                    path.unlink()
                    deleted_records += 1
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("gdpr_deletion_scan_failed", extra={"error": str(e)[:160]})

    logger.info(
        "deletion_processed", extra={"user_hash": user_hash, "deleted_records": deleted_records}
    )
    return {"success": True, "deleted_records": deleted_records, "user_hash": user_hash}
