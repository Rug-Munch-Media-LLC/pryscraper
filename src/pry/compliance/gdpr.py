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
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pry.compliance import record_store

# Re-exported so `from pry.compliance.gdpr import request_deletion` — used by
# the GDPR router — keeps working after the deletion concern was split out.
from pry.compliance.deletion import (  # noqa: F401
    execute_deletion,
    process_deletion,
    request_deletion,
)
from pry.core.paths import PRY_DATA_DIR

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
        logger.warning("gdpr_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


def check_consent(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    """Check if a user has given consent for a purpose."""
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    now = datetime.now(UTC)

    def _is_live_consent(record: dict[str, Any]) -> bool:
        if record.get("purpose") != purpose:
            return False
        return datetime.fromisoformat(record["expires_at"]) > now

    latest, read = record_store.find(
        list(CONSENT_DIR.glob(f"{user_hash}_*.json")), _is_live_consent
    )
    if latest is not None:
        result = {
            "consent_given": latest["consent_given"],
            "recorded_at": latest["recorded_at"],
            "expires_at": latest["expires_at"],
            "valid": True,
        }
        if read.count():
            result["unreadable_records"] = read.count()
        return result
    result = {"consent_given": False, "valid": False, "note": "No consent record found"}
    if read.count():
        # Records exist but could not be read, so "no record found" is false.
        result["note"] = f"No consent record found, but {read.note()}"
        result["unreadable_records"] = read.count()
    return result


def revoke_consent(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    """Revoke a user's consent for a purpose."""
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    revoked = 0
    unreadable: list[str] = []
    for path in CONSENT_DIR.glob(f"{user_hash}_*.json"):
        try:
            record = json.loads(path.read_text())
            if record.get("purpose") == purpose and record.get("consent_given"):
                record["consent_given"] = False
                record["revoked_at"] = datetime.now(UTC).isoformat()
                path.write_text(json.dumps(record, indent=2))
                revoked += 1
        except (json.JSONDecodeError, OSError):
            logger.warning("gdpr_suppressed", exc_info=True)
            unreadable.append(path.name)
            continue
    result: dict[str, Any] = {"success": True, "revoked_records": revoked}
    if unreadable:
        # success=True alone would claim a complete revocation. It is partial.
        result["unreadable_records"] = len(unreadable)
        result["note"] = (
            f"{len(unreadable)} consent record(s) could not be read or written; "
            "those may still hold consent"
        )
    return result


# ── Data Deletion (Right to Erasure) ──


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
    # Single-element list so the helpers below can accumulate without a
    # nonlocal; the count is read back once at the end.
    counter = [0]
    skipped: list[str] = []

    # Remove expired consent records
    for path in sorted(CONSENT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            expires = datetime.fromisoformat(data["expires_at"])
            if expires < datetime.now(UTC):
                path.unlink()
                counter[0] += 1
        except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError):
            # An expired record we cannot read is NOT removed. Count it so the
            # caller sees a partial sweep instead of a silently clean result.
            logger.warning("gdpr_suppressed", exc_info=True)
            skipped.append(path.name)
            continue

    # Remove old quality data (>90 days). Derived from PRY_DATA_DIR, matching
    # pry.engine.quality.QUALITY_DIR -- a "~/.pry/quality" spelling resolves
    # under $HOME, which in production is a different tree from PRY_DATA_DIR
    # and therefore an empty one.
    _remove_expired(PRY_DATA_DIR / "quality", 90 * 86400, now, counter, skipped)

    # Remove old fingerprints (>30 days). Same reasoning; the writer is
    # pry.engine.quality_checks.freshness under PRY_DATA_DIR / "freshness".
    _remove_expired(PRY_DATA_DIR / "freshness", 30 * 86400, now, counter, skipped)

    removed_total = counter[0]
    logger.info("retention_policy_applied", extra={"removed": removed_total})
    result: dict[str, Any] = {"success": True, "removed_records": removed_total}
    if skipped:
        # The sweep did not finish: unreadable records were left in place.
        result["unreadable_records"] = len(skipped)
    return result


def _remove_expired(
    directory: Path,
    max_age_s: int,
    now: float,
    removed: list[int],
    skipped: list[str],
) -> None:
    """Delete ``*.json`` under ``directory`` older than ``max_age_s``.

    Counts a file it could not stat or unlink into ``skipped`` rather than
    letting it vanish silently, so the caller can report a partial sweep.
    """
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            if now - path.stat().st_mtime > max_age_s:
                path.unlink()
                removed[0] += 1
        except OSError:
            logger.warning("gdpr_suppressed", exc_info=True)
            skipped.append(path.name)


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
        logger.warning("gdpr_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


class AuditLogUnavailableError(RuntimeError):
    """A log file in the requested window could not be read or parsed.

    Raised instead of silently dropping the file, because a partial audit
    extract reported as a complete one is a compliance defect, not a
    convenience.
    """


def get_audit_log(days_back: int = 7) -> list[dict[str, Any]]:
    """Get audit log entries for the specified period.

    Raises:
        AuditLogUnavailableError: a log file in the window was unreadable or
            contained a malformed line. An audit trail with a hole must not be
            returned as if it were whole.
    """
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
        except (json.JSONDecodeError, OSError) as exc:
            raise AuditLogUnavailableError(
                f"audit log {path.name} could not be read: {exc}"
            ) from exc
    return events
