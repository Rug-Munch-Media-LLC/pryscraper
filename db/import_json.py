"""Pry - one-shot JSON store -> SQL importer.

Reads the legacy JSON/JSONL stores under ``$PRY_DATA_DIR`` and writes them
into the SQL tables. Idempotent: re-running with the same data is safe
(upsert-style pattern via the unique constraints on ``_id`` columns).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from db.models import (
    Account,
    Actor,
    Agency,
    BrowserSession,
    IntelSnapshot,
    Monitor,
    Pipeline,
    QualityCheck,
    ReferralClick,
    ReferralConversion,
    ReferralInAppUsage,
    StructureSnapshot,
)
from db.session import session_scope
from paths import PRY_DATA_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

logger = logging.getLogger(__name__)


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError as e:
        logger.warning("jsonl_read_failed", extra={"path": str(path), "error": str(e)[:80]})


def _iter_json_files(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict):
                        yield d
            elif isinstance(data, dict):
                yield data
        except (json.JSONDecodeError, OSError):
            return
        return
    for f in path.glob("*.json"):
        yield from _iter_json_files(f)


def import_json_stores(data_dir: Path | None = None) -> dict[str, int]:
    """One-shot importer: read all JSON stores and write to the SQL tables.

    Returns a dict of {store_name: row_count_imported}.

    Idempotent: re-running with the same data is safe (uses upsert-style
    pattern via the unique constraints on _id columns).
    """
    data_dir = data_dir or PRY_DATA_DIR
    counts: dict[str, int] = {}

    with session_scope() as s:
        # Quality
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
        counts["quality"] = n

        # Intel (JSONL)
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
        counts["intel"] = n

        # Monitors (JSON files)
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
        counts["monitors"] = n

        # Accounts (JSON files)
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
        counts["accounts"] = n

        # Actors (JSON files)
        n = 0
        for rec in _iter_json_files(data_dir / "actors"):
            aid = rec.get("actor_id") or rec.get("id", "")
            s.add(
                Actor(
                    actor_id=aid[:64],
                    name=rec.get("name", ""),
                    description=rec.get("description", ""),
                    template_id=rec.get("template_id", ""),
                    code=rec.get("code", ""),
                    price_per_run=rec.get("price_per_run", 0.0),
                    visibility=rec.get("visibility", "private"),
                    schedule_cron=rec.get("schedule_cron", ""),
                    tags=rec.get("tags", []),
                    author=rec.get("author", ""),
                    run_count=rec.get("run_count", 0),
                    revenue_usd=rec.get("revenue_usd", 0.0),
                )
            )
            n += 1
        counts["actors"] = n

        # Pipelines (JSON files)
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
        counts["pipelines"] = n

        # Sessions (JSON files)
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
        counts["sessions"] = n

        # Agency + clients (JSON files)
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
        counts["agency"] = n

        # Structure snapshots (JSON files)
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
        counts["structure"] = n

        # Referral clicks (JSONL)
        n = 0
        for rec in _iter_jsonl(data_dir / "referrals" / "clicks.jsonl"):
            s.add(
                ReferralClick(
                    click_id=rec.get("id", "")[:64],
                    provider=rec.get("provider", "")[:64],
                    url=rec.get("url", ""),
                    source=rec.get("source", ""),
                    user_id=rec.get("user_id", ""),
                    converted=rec.get("converted", False),
                    conversion_value_usd=rec.get("conversion_value_usd", 0.0),
                )
            )
            n += 1
        counts["referral_clicks"] = n

        # Referral conversions (JSONL)
        n = 0
        for rec in _iter_jsonl(data_dir / "referrals" / "conversions.jsonl"):
            s.add(
                ReferralConversion(
                    click_id=rec.get("click_id", "")[:64],
                    provider=rec.get("provider", "")[:64],
                    revenue_usd=rec.get("revenue_usd", 0.0),
                    notes=rec.get("notes", ""),
                )
            )
            n += 1
        counts["referral_conversions"] = n

        # Referral in-app usage (JSONL)
        n = 0
        for rec in _iter_jsonl(data_dir / "referrals" / "in_app_usage.jsonl"):
            s.add(
                ReferralInAppUsage(
                    provider=rec.get("provider", "")[:64],
                    revenue_usd=rec.get("revenue_usd", 0.0),
                )
            )
            n += 1
        counts["referral_in_app_usage"] = n

    return counts
