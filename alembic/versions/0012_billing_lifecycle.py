"""billing lifecycle: invoice numbers + tax fields

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18 00:00:00.000000

Adds the missing invoice lifecycle surfaces:

1. ``hosting_invoices.invoice_number`` — human-readable
   ``INV-YYYYMM-NNNNNN``, allocated from ``invoice_number_sequences`` by an
   atomic ``INSERT ... ON CONFLICT ... RETURNING`` (never ``max() + 1``).
   Existing rows are backfilled in id order, per their ``created_at`` month.
   A unique index makes a duplicate number impossible at the database level.
2. Tax columns (``tax_amount``, ``tax_rate``, ``tax_country``,
   ``reverse_charge``), defaulting to zero / no country so existing rows are
   valid without a rewrite. ``tax_rate`` is a fraction (``0.20`` = 20 %%).

Downgrade is refusal-safe: dropping invoice numbers destroys the only
human-readable reference on issued invoices. It requires
``PRY_ALLOW_BILLING_DOWNGRADE=1``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hosting_invoices"
SEQ_TABLE = "invoice_number_sequences"
UX_NUMBER = "ix_hosting_invoices_invoice_number"
PREFIX = "INV"

_ALLOCATE = (
    "INSERT INTO invoice_number_sequences (period, last_value) VALUES (:period, 1) "
    "ON CONFLICT (period) DO UPDATE "
    "SET last_value = invoice_number_sequences.last_value + 1 "
    "RETURNING last_value"
)


def _inspect() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspect().get_table_names()


def _has_column(table: str, column: str) -> bool:
    return _has_table(table) and any(c["name"] == column for c in _inspect().get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return _has_table(table) and any(i["name"] == index for i in _inspect().get_indexes(table))


def _period(raw: Any) -> str:
    """YYYYMM from a DB datetime (Postgres) or string (SQLite); now on failure."""
    if isinstance(raw, datetime):
        return raw.strftime("%Y%m")
    text = str(raw or "")
    digits = text[:7].replace("-", "")
    return digits if len(digits) == 6 and digits.isdigit() else datetime.now(UTC).strftime("%Y%m")


def _allocate(period: str) -> str:
    value = op.get_bind().execute(sa.text(_ALLOCATE), {"period": period}).scalar_one()
    return f"{PREFIX}-{period}-{int(value):06d}"


def _add_columns() -> None:
    added = (
        sa.Column("invoice_number", sa.String(32), nullable=True),
        sa.Column("tax_amount", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(9, 6), nullable=False, server_default="0"),
        sa.Column("tax_country", sa.String(2), nullable=False, server_default=""),
        sa.Column("reverse_charge", sa.Boolean(), nullable=False, server_default="0"),
    )
    for column in added:
        if not _has_column(TABLE, column.name):
            op.add_column(TABLE, column)


def _backfill() -> None:
    """Number existing invoices in id order, per created_at month."""
    if not _has_table(TABLE):
        return
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, created_at, invoice_number FROM hosting_invoices "
            "WHERE invoice_number IS NULL ORDER BY id"
        )
    ).all()
    for row_id, created_at, _existing in rows:
        number = _allocate(_period(created_at))
        bind.execute(
            sa.text("UPDATE hosting_invoices SET invoice_number = :n WHERE id = :id"),
            {"n": number, "id": row_id},
        )


def upgrade() -> None:
    if not _has_table(SEQ_TABLE):
        op.create_table(
            SEQ_TABLE,
            sa.Column("period", sa.String(6), primary_key=True),
            sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        )
    _add_columns()
    _backfill()
    if not _has_index(TABLE, UX_NUMBER):
        op.create_index(UX_NUMBER, TABLE, ["invoice_number"], unique=True)


def downgrade() -> None:
    if os.environ.get("PRY_ALLOW_BILLING_DOWNGRADE", "0") != "1":
        raise RuntimeError(
            "0012 downgrade drops invoice_number and the tax columns. Issued invoices "
            "would lose their only human-readable reference. Set "
            "PRY_ALLOW_BILLING_DOWNGRADE=1 only with a verified backup."
        )
    if _has_index(TABLE, UX_NUMBER):
        op.drop_index(UX_NUMBER, table_name=TABLE)
    for column in ("reverse_charge", "tax_country", "tax_rate", "tax_amount", "invoice_number"):
        if _has_column(TABLE, column):
            op.drop_column(TABLE, column)
    if _has_table(SEQ_TABLE):
        op.drop_table(SEQ_TABLE)
