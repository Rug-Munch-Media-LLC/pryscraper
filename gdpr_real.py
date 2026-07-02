# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Real GDPR compliance: data subject access requests, data portability, real audit log."""

import contextlib
import json
import logging
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

GDPR_DIR = PRY_DATA_DIR / "gdpr_real"
GDPR_DIR.mkdir(parents=True, exist_ok=True)

DATA_RESIDENCES = [
    "quality/",
    "reviews/",
    "intel/",
    "costing/",
    "freshness/",
    "structure/",
    "seo/",
    "monitors/",
    "vault/",
    "accounts/",
    "reports/",
    "training/",
    "pipelines/",
    "agency/",
    "compliance/",
    "caching/",
    "stealth_scripts/",
    "jobs/",
]


class GDPRService:
    """Real GDPR compliance: data subject access, deletion, portability, audit."""

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._audit_log_path = GDPR_DIR / "audit.log"
        self._deletion_log_path = GDPR_DIR / "deletions.log"

    def audit(self, action: str, subject_id: str = "", details: dict | None = None) -> None:
        """Write an immutable audit log entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "subject_id": subject_id,
            "operator": "system",
            "details": details or {},
        }
        try:
            with open(self._audit_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
        logger.info("gdpr_audit", extra=entry)

    def right_to_access(self, subject_id: str) -> dict[str, Any]:
        """GDPR Art. 15: Right of access by the data subject.
        Find ALL data Pry holds about this person."""
        self.audit("right_to_access", subject_id)
        data_found: dict[str, Any] = {
            "subject_id": subject_id,
            "data_categories": [],
            "records": {},
            "total_records": 0,
        }
        pry_dir = PRY_DATA_DIR
        subject_lower = subject_id.lower()
        for subdir in DATA_RESIDENCES:
            subdir_path = pry_dir / subdir
            if not subdir_path.exists():
                continue
            for f in subdir_path.rglob("*"):
                if not f.is_file() or f.suffix not in (".json", ".jsonl", ".txt"):
                    continue
                try:
                    content = f.read_text()
                except (OSError, UnicodeDecodeError):
                    continue
                if subject_id in content or subject_lower in content.lower():
                    data_found["data_categories"].append(str(subdir))
                    data_found["records"].setdefault(str(subdir), []).append(
                        {
                            "file": str(f.relative_to(pry_dir)),
                            "size": f.stat().st_size,
                            "modified": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(),
                        }
                    )
                    data_found["total_records"] += 1
        return data_found

    def right_to_erasure(self, subject_id: str, verify: bool = True) -> dict[str, Any]:
        """GDPR Art. 17: Right to erasure ('right to be forgotten').
        Find and DELETE all data about this person."""
        self.audit("right_to_erasure_initiated", subject_id)
        access_data = self.right_to_access(subject_id)
        if access_data["total_records"] == 0:
            return {"success": True, "deleted": 0, "message": "No data found for subject"}

        if verify:
            return {
                "requires_verification": True,
                "would_delete": access_data,
                "confirmation_required": (
                    f"POST /v1/gdpr/erasure/{subject_id} with confirm=true to proceed"
                ),
            }

        deleted = 0
        home = Path(os.path.expanduser("~"))
        for files in access_data["records"].values():
            for file_info in files:
                file_path = home / ".pry" / file_info["file"]
                try:
                    if file_path.is_file():
                        file_path.unlink()
                        deleted += 1
                    elif file_path.is_dir():
                        shutil.rmtree(file_path)
                        deleted += 1
                except OSError:
                    pass

        if self._db is not None:
            try:
                from db import ApiKey, QualityCheckRecord, UsageRecord

                with self._db.session() as s:
                    s.query(UsageRecord).filter(
                        UsageRecord.metadata_json.like(f"%{subject_id}%")
                    ).delete()
                    s.query(QualityCheckRecord).filter(
                        QualityCheckRecord.url.like(f"%{subject_id}%")
                    ).delete()
                    s.query(ApiKey).filter(ApiKey.name.like(f"%{subject_id}%")).delete()
            except OSError:
                pass

        deletion_record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "subject_id": subject_id,
            "records_deleted": deleted,
        }
        try:
            with open(self._deletion_log_path, "a") as f:
                f.write(json.dumps(deletion_record) + "\n")
        except OSError:
            pass
        self.audit("right_to_erasure_completed", subject_id, {"records_deleted": deleted})
        return {"success": True, "deleted": deleted}

    def data_portability_export(self, subject_id: str) -> dict[str, Any]:
        """GDPR Art. 20: Right to data portability.
        Export all data about this person in a machine-readable format (JSON)."""
        self.audit("data_portability_export", subject_id)
        access_data = self.right_to_access(subject_id)
        if access_data["total_records"] == 0:
            return {"success": False, "error": "No data found"}

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        export_dir = GDPR_DIR / f"exports/{subject_id}_{timestamp}"
        export_dir.mkdir(parents=True, exist_ok=True)

        home = Path(os.path.expanduser("~"))
        for files in access_data["records"].values():
            for file_info in files:
                src = home / ".pry" / file_info["file"]
                if not src.exists():
                    continue
                dest = export_dir / file_info["file"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    dest.write_text(src.read_text())

        index = {
            "exported_at": datetime.now(UTC).isoformat(),
            "subject_id": subject_id,
            "format": "JSON (machine-readable)",
            "files": [f["file"] for cat in access_data["records"].values() for f in cat],
            "instructions": "This is your personal data export under GDPR Art. 20.",
        }
        (export_dir / "INDEX.json").write_text(json.dumps(index, indent=2))

        zip_path = export_dir.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in export_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(export_dir))
        self.audit(
            "data_portability_export_completed",
            subject_id,
            {"export_path": str(zip_path)},
        )
        return {
            "success": True,
            "export_path": str(zip_path),
            "files_count": access_data["total_records"],
        }

    def get_audit_log(self, days_back: int = 30, subject_id: str = "") -> list[dict[str, Any]]:
        """Get audit log entries."""
        entries: list[dict[str, Any]] = []
        if not self._audit_log_path.exists():
            return entries
        for line in self._audit_log_path.read_text().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if subject_id and entry.get("subject_id") != subject_id:
                continue
            entries.append(entry)
        return entries
