"""Per-store steps for the one-shot JSON store importer (core stores).

Split from import_json.py on 2026-10-05 to decompose the ~218-line
``import_json_stores`` orchestrator. Each ``add_*_rows`` function owns exactly
one store: it iterates that store's file(s) and adds one ORM row per record,
returning the number of rows added. The orchestrator sequences them.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING

from pry.core.db.import_json_iterators import _iter_json_files, _iter_jsonl
from pry.core.db.models import (
    Account,
    Agency,
    BrowserSession,
    IntelSnapshot,
    Monitor,
    Pipeline,
    QualityCheck,
    StructureSnapshot,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from sqlalchemy.orm import Session


def add_quality_rows(s: Session, data_dir: Path) -> int:
    """Add QualityCheck rows from ``quality/checks.jsonl``."""
    n = 0
    for rec in _iter_jsonl(data_dir / "quality" / "checks.jsonl"):
        s.add(
            QualityCheck(
                extraction_id=rec.get("extraction_id", rec.get("id", ""))[:64],
                url=rec.get("url", ""),
                completeness=rec.get("completeness", 0.0),
                accuracy=rec.get("accuracy", 0.0),
                freshness=rec.get("freshness", 0.0),
                overall_score=rec.get("overall_score", 0.0),
                risk_level=rec.get("risk_level", "unknown"),
                issues=rec.get("issues", []),
                data=rec,
            )
        )
        n += 1
    return n


def add_intel_rows(s: Session, data_dir: Path) -> int:
    """Add IntelSnapshot rows from ``intel/snapshots.jsonl``."""
    n = 0
    for rec in _iter_jsonl(data_dir / "intel" / "snapshots.jsonl"):
        s.add(
            IntelSnapshot(
                competitor_id=rec.get("competitor_id", "")[:64],
                competitor_name=rec.get("competitor_name", "")[:256],
                url=rec.get("url", ""),
                fields=rec.get("fields", {}),
            )
        )
        n += 1
    return n


def add_monitor_rows(s: Session, data_dir: Path) -> int:
    """Add Monitor rows from ``monitors/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "monitors"):
        mid = rec.get("monitor_id") or rec.get("id", "")
        s.add(
            Monitor(
                monitor_id=mid[:64],
                url=rec.get("url", ""),
                monitor_name=rec.get("name", ""),  # was 'name' in JSON
                schedule_cron=rec.get("schedule_cron", ""),
                check_type=rec.get("check_type", "content"),
                active=rec.get("active", True),
                webhook_url=rec.get("webhook_url", ""),
            )
        )
        n += 1
    return n


def add_account_rows(s: Session, data_dir: Path) -> int:
    """Add Account rows from ``accounts/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "accounts"):
        aid = rec.get("account_id") or rec.get("id", "")
        s.add(
            Account(
                account_id=aid[:64],
                service=rec.get("service", "unknown")[:64],
                username=rec.get("username", ""),
                email=rec.get("email", ""),
                status=rec.get("status", "active"),
                used_count=rec.get("used_count", 0),
            )
        )
        n += 1
    return n


def add_pipeline_rows(s: Session, data_dir: Path) -> int:
    """Add Pipeline rows from ``pipelines/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "pipelines"):
        pid = rec.get("pipeline_id") or rec.get("id", "")
        s.add(
            Pipeline(
                pipeline_id=pid[:64],
                pipeline_name=rec.get("name", ""),
                steps=rec.get("steps", []),
                schedule_cron=rec.get("schedule_cron", ""),
                active=rec.get("active", True),
            )
        )
        n += 1
    return n


def add_session_rows(s: Session, data_dir: Path) -> int:
    """Add BrowserSession rows from ``sessions/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "sessions"):
        sid = rec.get("session_id") or rec.get("id", "")
        s.add(
            BrowserSession(
                session_id=sid[:64],
                cookies=rec.get("cookies", []),
                local_storage=rec.get("local_storage", {}),
                user_agent=rec.get("user_agent", ""),
                proxy=rec.get("proxy", ""),
            )
        )
        n += 1
    return n


def add_agency_rows(s: Session, data_dir: Path) -> int:
    """Add Agency rows from ``agency/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "agency"):
        aid = rec.get("agency_id") or rec.get("id", "")
        s.add(
            Agency(
                agency_id=aid[:64],
                agency_name=rec.get("name", ""),
                owner_email=rec.get("owner_email", ""),
                custom_domain=rec.get("custom_domain", ""),
                brand_color=rec.get("brand_color", "#f59e0b"),
                logo_url=rec.get("logo_url", ""),
                quota=rec.get("quota", 10000),
            )
        )
        n += 1
    return n


def add_structure_rows(s: Session, data_dir: Path) -> int:
    """Add StructureSnapshot rows from ``structure/*.json``."""
    n = 0
    for rec in _iter_json_files(data_dir / "structure"):
        s.add(
            StructureSnapshot(
                url=rec.get("url", ""),
                url_hash=rec.get("url_hash", ""),
                template_id=rec.get("template_id", ""),
                structure_hash=rec.get("structure_hash", ""),
                selectors=rec.get("selectors", []),
                all_matched=rec.get("all_matched", False),
                matched_count=rec.get("matched_count", 0),
                failed_count=rec.get("failed_count", 0),
                changes=rec.get("changes", []),
                change_count=rec.get("change_count", 0),
                has_changes=rec.get("has_changes", False),
                dom_summary=rec.get("dom_summary", {}),
            )
        )
        n += 1
    return n
