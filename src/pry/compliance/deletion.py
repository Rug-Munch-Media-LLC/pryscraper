"""GDPR erasure (Art. 17): request, scan and execute deletion of user data.

Split out of ``gdpr`` so the consent/retention/audit concerns stay legible on
their own. Re-exported from ``pry.compliance.gdpr`` so every existing
``from pry.compliance.gdpr import request_deletion`` keeps working.
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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

GDPR_DIR = PRY_DATA_DIR / "gdpr"
GDPR_DIR.mkdir(parents=True, exist_ok=True)
DELETION_DIR = GDPR_DIR / "deletion"
DELETION_DIR.mkdir(exist_ok=True)
CONSENT_DIR = GDPR_DIR / "consent"


async def request_deletion(
    user_id: str,
    reason: str = "user_request",
    requested_by: str = "user",
) -> dict[str, Any]:
    """Request deletion of all data associated with a user (GDPR Art. 17).

    Args:
        user_id: User identifier (email, ID, or hash)
        reason: Deletion reason
        requested_by: Who requested the deletion (user, admin, automated)
    """
    request_id = uuid.uuid4().hex[:12]
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    deletion_request = {
        "id": request_id,
        "user_id": user_id,
        "user_hash": user_hash,
        "reason": reason,
        "requested_by": requested_by,
        "status": "pending",
        "requested_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "deleted_records": 0,
    }
    path = DELETION_DIR / f"{request_id}.json"
    try:
        path.write_text(json.dumps(deletion_request, indent=2))
        logger.info("deletion_requested", extra={"user_hash": user_hash, "reason": reason})
        return deletion_request
    except OSError as e:
        return {"error": str(e)}


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


async def execute_deletion(request_id: str) -> dict[str, Any]:
    """Execute a deletion request."""
    path = DELETION_DIR / f"{request_id}.json"
    if not path.exists():
        return {"error": f"Deletion request not found: {request_id}"}

    try:
        request: dict[str, Any] = json.loads(path.read_text())
        user_id = request.get("user_id", "")
        result = process_deletion(user_id)
        request["status"] = "completed"
        request["completed_at"] = datetime.now(UTC).isoformat()
        request["deleted_records"] = result.get("deleted_records", 0)
        path.write_text(json.dumps(request, indent=2))
        return request
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


# ── Retention Policies ──
