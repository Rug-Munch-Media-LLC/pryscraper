# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for ``pry.core.db.import_json`` — malformed, duplicate and unreadable.

Happy-path and empty-store cases live in ``test_db_import_json``. These cases
pin down that failures surface instead of importing as a clean short count.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.support.db_import import temp_data_dir, write_json, write_jsonl  # noqa: F401


def test_import_invalid_json_lines_raise_rather_than_import_a_short_count(
    temp_data_dir,
):
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

    write_jsonl(
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

    write_json(
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
