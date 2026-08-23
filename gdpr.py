"""Pry — GDPR Compliance Portal.
Data deletion API, consent management, retention policies, audit log."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

GDPR_DIR = PRY_DATA_DIR / "gdpr"
GDPR_DIR.mkdir(parents=True, exist_ok=True)

CONSENT_DIR = GDPR_DIR / "consent"
CONSENT_DIR.mkdir(exist_ok=True)

DELETION_DIR = GDPR_DIR / "deletions"
DELETION_DIR.mkdir(exist_ok=True)

AUDIT_DIR = GDPR_DIR / "audit"
AUDIT_DIR.mkdir(exist_ok=True)

RETENTION_DIR = GDPR_DIR / "retention"
RETENTION_DIR.mkdir(exist_ok=True)


# ── Consent Management ──


async def record_consent(
    user_id: str,
    purpose: str = "data_collection",
    consent_given: bool = True,
    ip_address: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """Record a user's consent for data processing.

    Args:
        user_id: User identifier (email, ID, or hash)
        purpose: GDPR processing purpose
        consent_given: Whether consent was given
        ip_address: User IP at time of consent
        user_agent: User agent at time of consent
    """
    record_id = uuid.uuid4().hex[:12]
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    record = {
        "id": record_id,
        "user_id": user_id,
        "user_hash": user_hash,
        "purpose": purpose,
        "consent_given": consent_given,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "recorded_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=365)).isoformat(),
    }
    path = CONSENT_DIR / f"{user_hash}_{record_id}.json"
    try:
        path.write_text(json.dumps(record, indent=2))
        logger.info(
            "consent_recorded",
            extra={"user_hash": user_hash, "purpose": purpose, "consent": consent_given},
        )
        return {"success": True, "record_id": record_id, "consent": record}
    except OSError as e:
        return {"success": False, "error": str(e)}


def check_consent(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    """Check if a user has given consent for a purpose."""
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    now = datetime.now(UTC)

    latest_consent = None
    for path in sorted(CONSENT_DIR.glob(f"{user_hash}_*.json"), key=os.path.getmtime, reverse=True):
        try:
            record = json.loads(path.read_text())
            if record.get("purpose") == purpose:
                expires = datetime.fromisoformat(record["expires_at"])
                if expires > now:
                    latest_consent = record
                    break
        except (json.JSONDecodeError, OSError):
            continue

    if latest_consent:
        return {
            "consent_given": latest_consent["consent_given"],
            "recorded_at": latest_consent["recorded_at"],
            "expires_at": latest_consent["expires_at"],
            "valid": True,
        }
    return {"consent_given": False, "valid": False, "note": "No consent record found"}


def revoke_consent(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    """Revoke a user's consent for a purpose."""
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    revoked = 0
    for path in CONSENT_DIR.glob(f"{user_hash}_*.json"):
        try:
            record = json.loads(path.read_text())
            if record.get("purpose") == purpose and record.get("consent_given"):
                record["consent_given"] = False
                record["revoked_at"] = datetime.now(UTC).isoformat()
                path.write_text(json.dumps(record, indent=2))
                revoked += 1
        except (json.JSONDecodeError, OSError):
            continue
    return {"success": True, "revoked_records": revoked}


# ── Data Deletion (Right to Erasure) ──


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


def process_deletion(user_id: str) -> dict[str, Any]:
    """Process data deletion for a user (GDPR Art. 17).

    This finds and removes all data associated with the user across
    Pry's storage: consent records, quality history, sessions, etc.
    """
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
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
                url = data.get("url", "")
                if user_id.lower() in url.lower():
                    path.unlink()
                    deleted_records += 1
            except (json.JSONDecodeError, OSError):
                pass

    # Delete sessions associated with this user
    sessions_dir = Path(os.path.expanduser("~/.pry/sessions"))
    if sessions_dir.exists():
        for path in sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                meta = data.get("metadata", {})
                if user_id.lower() in str(meta).lower():
                    path.unlink()
                    deleted_records += 1
            except (json.JSONDecodeError, OSError):
                pass

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


def get_retention_policy() -> dict[str, Any]:
    """Get the current data retention policy."""
    return {
        "consent_records": "365 days",
        "quality_history": "90 days",
        "sessions": "30 days",
        "audit_logs": "365 days",
        "fingerprints": "30 days",
        "monitor_snapshots": "90 days",
    }


async def apply_retention_policy() -> dict[str, Any]:
    """Apply the retention policy by removing expired data."""
    # Retention cleanup is blocking file I/O (glob/stat/unlink) — run off-loop.
    return await asyncio.to_thread(_apply_retention_policy_sync)


def _apply_retention_policy_sync() -> dict[str, Any]:
    """Apply the retention policy by removing expired data (sync worker)."""
    now = time.time()
    removed_total = 0

    # Remove expired consent records
    for path in CONSENT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            expires = datetime.fromisoformat(data["expires_at"])
            if expires < datetime.now(UTC):
                path.unlink()
                removed_total += 1
        except (json.JSONDecodeError, OSError, ValueError):
            continue

    # Remove old quality data (>90 days)
    quality_dir = Path(os.path.expanduser("~/.pry/quality"))
    if quality_dir.exists():
        for path in quality_dir.glob("*.json"):
            if now - path.stat().st_mtime > 90 * 86400:
                path.unlink()
                removed_total += 1

    # Remove old fingerprints (>30 days)
    freshness_dir = Path(os.path.expanduser("~/.pry/freshness"))
    if freshness_dir.exists():
        for path in freshness_dir.glob("*.json"):
            if now - path.stat().st_mtime > 30 * 86400:
                path.unlink()
                removed_total += 1

    logger.info("retention_policy_applied", extra={"removed": removed_total})
    return {"success": True, "removed_records": removed_total}


# ── Audit Log ──


async def log_audit_event(
    action: str,
    user_id: str = "system",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Log an audit event for compliance purposes."""
    event_id = uuid.uuid4().hex[:12]
    event = {
        "id": event_id,
        "action": action,
        "user_id": user_id,
        "details": details or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    daily = AUDIT_DIR / f"audit_{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
    try:
        with open(daily, "a") as f:  # noqa: ASYNC230 - single-line JSONL append, tiny & infrequent
            f.write(json.dumps(event) + "\n")
        return {"success": True, "event_id": event_id}
    except OSError as e:
        return {"success": False, "error": str(e)}


def get_audit_log(days_back: int = 7) -> list[dict[str, Any]]:
    """Get audit log entries for the specified period."""
    cutoff = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    events = []
    for path in sorted(AUDIT_DIR.glob("audit_*.jsonl"), reverse=True):
        date_str = path.stem.replace("audit_", "")
        if date_str < cutoff:
            break
        try:
            for line in path.read_text().splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            continue
    return events
