"""Tests for ``pry.core.db.import_json`` — the one-shot JSON store importer.

Covers ``import_json_stores()`` plus the ``_iter_jsonl`` / ``_iter_json_files``
helpers with concrete assertions on row counts and field values. Uses a temp
SQLite DB so the user's real data dir is never touched.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import pry.core.paths as paths


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db

    importlib.reload(paths)
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    yield tmp_path
    db._engine = None
    db._SessionLocal = None


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── import_json_stores: happy path ────────────────────────────────


def test_import_valid_json_creates_rows_with_field_values(temp_data_dir):
    """Valid JSON stores are written to SQL with concrete field values."""
    import pry.core.db as db

    # Quality (JSONL)
    _write_jsonl(
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
    # Intel (JSONL)
    _write_jsonl(
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
    # Monitors (JSON files)
    _write_json(
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
    # Actors (JSON files)
    _write_json(
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

    counts = db.import_json_stores(data_dir=temp_data_dir)
    assert counts["quality"] == 1
    assert counts["intel"] == 1
    assert counts["monitors"] == 1
    assert counts["actors"] == 1

    # Concrete field-value assertions.
    with db.session_scope() as s:
        q = s.execute(
            select(db.QualityCheck).where(db.QualityCheck.extraction_id == "q1")
        ).scalar_one()
        assert q.url == "https://example.com"
        assert q.completeness == 0.9
        assert q.risk_level == "low"
        assert q.issues == ["slow"]

        i = s.execute(
            select(db.IntelSnapshot).where(db.IntelSnapshot.competitor_id == "acme")
        ).scalar_one()
        assert i.competitor_name == "Acme Corp"
        assert i.fields == {"price": 99.99}

        m = s.execute(select(db.Monitor).where(db.Monitor.monitor_id == "m1")).scalar_one()
        # 'name' from JSON is renamed to 'monitor_name' in SQL.
        assert m.monitor_name == "Example Monitor"
        assert m.schedule_cron == "0 * * * *"
        assert m.active is True
        assert m.webhook_url == "https://hooks.example.com/1"

        a = s.execute(select(db.Actor).where(db.Actor.actor_id == "a1")).scalar_one()
        assert a.name == "Scraper"
        assert a.price_per_run == 0.5
        assert a.visibility == "public"
        assert a.tags == ["scrape"]
        assert a.run_count == 3
        assert a.revenue_usd == 1.5


# ── import_json_stores: error / edge cases ───────────────────────


def test_import_invalid_json_lines_raise_rather_than_import_a_short_count(temp_data_dir):
    """A malformed JSONL line aborts the import instead of reporting a short success."""
    import pry.core.db as db

    path = temp_data_dir / "intel" / "snapshots.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "{not valid json}\n"
        + json.dumps({"competitor_id": "ok", "competitor_name": "OK", "url": "https://ok.com"})
        + "\n"
        + "also not json\n",
        encoding="utf-8",
    )

    # Previously this returned counts["intel"] == 1 and committed one row —
    # a clean-looking import that silently lost two records.
    with pytest.raises(ValueError, match="malformed JSONL"):
        db.import_json_stores(data_dir=temp_data_dir)

    with db.session_scope() as s:
        rows = s.execute(select(db.IntelSnapshot)).scalars().all()
        assert rows == []


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


# ── import_json_stores: duplicate / idempotency ──────────────────


def test_import_duplicate_intel_creates_duplicate_rows(temp_data_dir):
    """Stores without a unique _id constraint are NOT idempotent on re-import.

    [REVIEW] The module docstring claims the importer is idempotent, but
    ``import_json_stores`` uses plain ``s.add()`` (INSERT). Tables without a
    unique constraint on their _id column (intel_snapshots, quality_checks,
    structure_snapshots, referral_conversions, referral_in_app_usage) will
    accumulate duplicate rows on every re-run. This test documents that
    behavior so the discrepancy is visible.
    """
    import pry.core.db as db

    _write_jsonl(
        temp_data_dir / "intel" / "snapshots.jsonl",
        [{"competitor_id": "acme", "competitor_name": "Acme", "url": "https://acme.com"}],
    )

    first = db.import_json_stores(data_dir=temp_data_dir)
    assert first["intel"] == 1

    second = db.import_json_stores(data_dir=temp_data_dir)
    assert second["intel"] == 1  # count reflects this run's inserts

    with db.session_scope() as s:
        rows = s.execute(select(db.IntelSnapshot)).scalars().all()
        assert len(rows) == 2  # duplicate rows accumulated


def test_import_duplicate_monitor_raises_integrity_error(temp_data_dir):
    """Stores with a unique _id constraint raise IntegrityError on re-import.

    [REVIEW] For unique-constrained tables (monitors, actors, accounts, ...),
    re-importing the same data raises IntegrityError because the code does a
    plain INSERT, not an upsert. The docstring's "idempotent" claim does not
    hold here.
    """
    import pry.core.db as db

    _write_json(
        temp_data_dir / "monitors" / "m1.json",
        {"monitor_id": "m1", "url": "https://example.com", "name": "M1"},
    )

    first = db.import_json_stores(data_dir=temp_data_dir)
    assert first["monitors"] == 1

    with pytest.raises(IntegrityError):
        db.import_json_stores(data_dir=temp_data_dir)


# ── import_json_stores: swallowed-read failures raise ──────────────
#
# A read error that yields nothing instead of raising becomes a
# ``counts[store] = 0`` entry, which reads as "nothing to import" rather
# than "this store's data was lost". The importer must surface it.


def test_import_json_stores_surfaces_unreadable_store(temp_data_dir):
    """A corrupt store must not import as a clean 0-row success."""
    from pry.core.db.import_json import import_json_stores

    monitors = temp_data_dir / "monitors"
    monitors.mkdir(parents=True, exist_ok=True)
    (monitors / "m1.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable JSON store"):
        import_json_stores(temp_data_dir)
