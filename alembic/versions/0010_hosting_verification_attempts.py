"""hosting_invoices.verification_attempts — bound verification guessing.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18 00:00:00.000000

``verify_hosting_email`` now counts wrong codes and locks an invoice after
five attempts. The counter must survive process restarts, so it is a column.

SQLite/Postgres safe: additive column with a non-NULL server default, guarded
by a schema inspection so a DB that already ran ``create_all`` is untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hosting_invoices"
COLUMN = "verification_attempts"


def _has_column(table: str, column: str) -> bool:
    """True when *column* already exists (cached reflection goes stale)."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
