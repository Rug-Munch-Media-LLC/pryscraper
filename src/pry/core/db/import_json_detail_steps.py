"""Per-store steps for the one-shot JSON store importer (actor + referral).

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
    Actor,
    ReferralClick,
    ReferralConversion,
    ReferralInAppUsage,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from sqlalchemy.orm import Session


def add_actor_rows(s: Session, data_dir: Path) -> int:
    """Add Actor rows from ``actors/*.json``."""
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
    return n


def add_referral_click_rows(s: Session, data_dir: Path) -> int:
    """Add ReferralClick rows from ``referrals/clicks.jsonl``."""
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
    return n


def add_referral_conversion_rows(s: Session, data_dir: Path) -> int:
    """Add ReferralConversion rows from ``referrals/conversions.jsonl``."""
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
    return n


def add_referral_in_app_rows(s: Session, data_dir: Path) -> int:
    """Add ReferralInAppUsage rows from ``referrals/in_app_usage.jsonl``."""
    n = 0
    for rec in _iter_jsonl(data_dir / "referrals" / "in_app_usage.jsonl"):
        s.add(
            ReferralInAppUsage(
                provider=rec.get("provider", "")[:64],
                revenue_usd=rec.get("revenue_usd", 0.0),
            )
        )
        n += 1
    return n
