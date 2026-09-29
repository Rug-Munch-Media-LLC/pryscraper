"""GDPR erasure (Art. 17): request, scan and execute deletion of user data.

Split out of ``gdpr`` so the consent/retention/audit concerns stay legible on
their own. Re-exported from ``pry.compliance.gdpr`` so every existing
``from pry.compliance.gdpr import request_deletion`` keeps working.

This module is the plumbing: record the request, execute it, report the outcome.
What a request actually removes lives in :mod:`pry.compliance.deletion_logic`,
whose helpers are re-exported here so every existing import path still resolves.
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
import uuid
from datetime import UTC, datetime
from typing import Any

from pry.compliance.deletion_logic import (  # noqa: F401
    MIN_USER_ID_LENGTH,
    _record_user_id,
    _word_boundary_match,
    process_deletion,
)
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
