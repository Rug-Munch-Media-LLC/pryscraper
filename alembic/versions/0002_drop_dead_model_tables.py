"""drop dead model tables — remove 11 models with zero live consumers

Downgrade recreates the empty tables but cannot restore rows: it refuses
unless acknowledged, and refuses when a table still holds rows.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14 00:00:00.000000
"""

from __future__ import annotations

import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

_DROPPED_TABLES = (
    "review_items",
    "costing_entries",
    "freshness_snapshots",
    "seo_snapshots",
    "training_datasets",
    "pipeline_runs",
    "gdpr_requests",
    "agency_clients",
    "actor_runs",
    "llm_usage",
    "x402_receipts",
)

# Column definitions used by downgrade to rebuild each table EMPTY.
_SPEC = spec_from_file_location(
    "_pry_0002_tables", Path(__file__).resolve().parents[1] / "_0002_tables.py"
)
assert _SPEC is not None
assert _SPEC.loader is not None
_tables = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_tables)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop child tables before parents (none of the parents are dropped,
    # but keeping order consistent with 0001's downgrade anyway).
    op.drop_table("x402_receipts")
    op.drop_table("llm_usage")
    op.drop_table("actor_runs")
    op.drop_table("agency_clients")
    op.drop_table("gdpr_requests")
    op.drop_table("pipeline_runs")
    op.drop_table("training_datasets")
    op.drop_table("seo_snapshots")
    op.drop_table("freshness_snapshots")
    op.drop_table("costing_entries")
    op.drop_table("review_items")


def _require_lossy_ack() -> None:
    """Downgrade rebuilds eleven tables EMPTY; require an explicit opt-in."""
    if os.environ.get("PRY_ALLOW_LOSSY_DOWNGRADE", "0") != "1":
        raise RuntimeError(
            "0002 downgrade recreates eleven dropped tables EMPTY; the deleted "
            "rows cannot be restored. Set PRY_ALLOW_LOSSY_DOWNGRADE=1 (with a "
            "verified backup) to acknowledge the loss."
        )


def _populated_tables(insp: Any) -> list[str]:
    """Tables that still exist AND hold rows (a recreate would discard them)."""
    populated = []
    for table in _DROPPED_TABLES:
        if table not in insp.get_table_names():
            continue
        stmt = sa.text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608  # nosec B608
        count = op.get_bind().execute(stmt).scalar()
        if count:
            populated.append(f"{table}({count})")
    return populated


def _refuse_if_populated(insp: Any) -> None:
    populated = _populated_tables(insp)
    if populated:
        raise RuntimeError(
            "0002 downgrade refused: these tables exist and hold rows that a "
            "recreate would discard: " + ", ".join(populated)
        )


def _recreate_tables() -> None:
    """Recreate the dropped tables (empty) so `alembic downgrade 0001` works."""
    _tables.create_tables(op)


def downgrade() -> None:
    """Recreate the dropped tables EMPTY; refuse when that would lose rows."""
    _require_lossy_ack()
    _refuse_if_populated(sa.inspect(op.get_bind()))
    _recreate_tables()
