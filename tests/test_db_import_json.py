# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for ``pry.core.db.import_json`` — happy path, empty and missing stores.

Uses a temp SQLite DB so the user's real data dir is never touched. Error and
idempotency cases live in ``test_db_import_json_errors``.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.support.db_import import temp_data_dir, write_json, write_jsonl  # noqa: F401

# ── import_json_stores: happy path ────────────────────────────────


def _seed_quality_and_intel(temp_data_dir):
    """Write one quality-check JSONL row and one intel-snapshot JSONL row."""
    write_jsonl(
        temp_data_dir / "quality" / "checks.jsonl",
        [
            {
                "extraction_id": "q1",
                "url": "https://example.com",
                "completeness": 0.9,
                "accuracy": 0.8,
                "freshness": 0.7,
                "overall_score": 0.85,
                "risk_level": "low",
                "issues": ["slow"],
            }
        ],
    )
    write_jsonl(
        temp_data_dir / "intel" / "snapshots.jsonl",
        [
            {
                "competitor_id": "acme",
                "competitor_name": "Acme Corp",
                "url": "https://acme.com",
                "fields": {"price": 99.99},
            }
        ],
    )


def _seed_monitors_and_actors(temp_data_dir):
    """Write one monitor JSON file and one actor JSON file."""
    write_json(
        temp_data_dir / "monitors" / "m1.json",
        {
            "monitor_id": "m1",
            "url": "https://example.com",
            "name": "Example Monitor",
            "schedule_cron": "0 * * * *",
            "check_type": "content",
            "active": True,
            "webhook_url": "https://hooks.example.com/1",
        },
    )
    write_json(
        temp_data_dir / "actors" / "a1.json",
        {
            "actor_id": "a1",
            "name": "Scraper",
            "price_per_run": 0.5,
            "visibility": "public",
            "tags": ["scrape"],
            "run_count": 3,
            "revenue_usd": 1.5,
        },
    )


def _assert_quality_row(q) -> None:
    assert q.url == "https://example.com"
    assert q.completeness == 0.9
    assert q.risk_level == "low"
    assert q.issues == ["slow"]


def _assert_intel_row(i) -> None:
    assert i.competitor_name == "Acme Corp"
    assert i.fields == {"price": 99.99}


def test_import_valid_json_creates_rows_with_field_values(temp_data_dir):
    """Valid JSON stores are written to SQL with concrete field values."""
    import pry.core.db as db

    _seed_quality_and_intel(temp_data_dir)
    _seed_monitors_and_actors(temp_data_dir)

    counts = db.import_json_stores(data_dir=temp_data_dir)
    assert counts["quality"] == 1
    assert counts["intel"] == 1
    assert counts["monitors"] == 1
    assert counts["actors"] == 1

    with db.session_scope() as s:
        q = s.execute(
            select(db.QualityCheck).where(db.QualityCheck.extraction_id == "q1")
        ).scalar_one()
        _assert_quality_row(q)

        i = s.execute(
            select(db.IntelSnapshot).where(db.IntelSnapshot.competitor_id == "acme")
        ).scalar_one()
        _assert_intel_row(i)


def _assert_monitor(m) -> None:
    assert m.monitor_name == "Example Monitor"
    assert m.schedule_cron == "0 * * * *"
    assert m.active is True
    assert m.webhook_url == "https://hooks.example.com/1"


def _assert_actor(a) -> None:
    assert a.name == "Scraper"
    assert a.price_per_run == 0.5
    assert a.visibility == "public"
    assert a.tags == ["scrape"]
    assert a.run_count == 3


def test_import_renames_monitor_and_actor_fields(temp_data_dir):
    """Renamed and scalar fields survive the JSON -> SQL mapping."""
    import pry.core.db as db

    _seed_monitors_and_actors(temp_data_dir)
    db.import_json_stores(data_dir=temp_data_dir)

    with db.session_scope() as s:
        m = s.execute(select(db.Monitor).where(db.Monitor.monitor_id == "m1")).scalar_one()
        _assert_monitor(m)
        a = s.execute(select(db.Actor).where(db.Actor.actor_id == "a1")).scalar_one()
        _assert_actor(a)
        assert a.revenue_usd == 1.5


# ── import_json_stores: empty / missing stores ───────────────────


def test_import_empty_data_no_crash(temp_data_dir):
    """Empty/missing stores import cleanly with zero counts."""
    import pry.core.db as db

    counts = db.import_json_stores(data_dir=temp_data_dir)
    # Every store key is present and zero.
    for key in (
        "quality",
        "intel",
        "monitors",
        "accounts",
        "actors",
        "pipelines",
        "sessions",
        "agency",
        "structure",
        "referral_clicks",
        "referral_conversions",
        "referral_in_app_usage",
    ):
        assert counts[key] == 0


def test_import_missing_data_dir_no_crash(temp_data_dir):
    """A data_dir that does not exist imports cleanly with zero counts."""
    import pry.core.db as db

    missing = temp_data_dir / "does-not-exist"
    counts = db.import_json_stores(data_dir=missing)
    assert counts["intel"] == 0
    assert counts["monitors"] == 0
