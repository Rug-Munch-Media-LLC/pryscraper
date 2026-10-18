"""money integrity: NUMERIC(18,6) + ledger idempotency

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18 00:00:00.000000

Three defects are closed here:

1. Money was ``FLOAT`` in the ledger path (``balances.balance_usd``,
   ``ledger_entries.delta_usd`` / ``balance_after``, ``hosting_invoices``,
   ``hosting_plans`` and both x402 records). Binary floats leave residue in a
   balance that is reconciled by subtraction. Every column becomes
   ``NUMERIC(18,6)``; the atomic-integer/string columns
   (``amount_atomic`` / ``required_amount_atomic``) remain the source of truth
   for settlement.

2. ``ledger_entries.reference`` had no uniqueness, so two workers crediting
   the same payment wrote two rows and added the money twice. A partial
   UNIQUE index on ``(user_id, reason, reference)`` — partial because a blank
   reference means "no idempotency key" (usage debits) — makes the database
   the arbiter. A plain index on ``reference`` serves lookups by payment id.

3. A duplicate set that would abort index creation is NOT deleted silently.
   The upgrade refuses with the offending keys, because deleting money rows
   to make a deploy pass is data loss disguised as a migration.

Downgrade is refusal-safe: NUMERIC -> FLOAT is lossy, so it requires
``PRY_ALLOW_LOSSY_DOWNGRADE=1``.

SQLite note: SQLite has no ALTER COLUMN TYPE. The type step is skipped there
by design (declared affinity only; the models declare NUMERIC and SQLAlchemy
converts to Decimal on read). The index steps run on both dialects.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY_TYPE = sa.Numeric(18, 6)
OLD_TYPE = sa.Float()

# (table, column, nullable) — the ledger/billing money surface.
MONEY_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("balances", "balance_usd", False),
    ("balances", "low_balance_threshold_usd", False),
    ("ledger_entries", "delta_usd", False),
    ("ledger_entries", "balance_after", False),
    ("hosting_plans", "price_usd_monthly", True),
    ("hosting_invoices", "amount_usd", False),
    ("x402_payment_records", "amount_usd", True),
    ("x402_settlement_records", "amount_usd", True),
)

LEDGER = "ledger_entries"
UX_LEDGER = "ux_ledger_user_reason_reference"
IX_LEDGER_REF = "ix_ledger_entries_reference"
_PARTIAL = "reference <> ''"

UPGRADE_HINT = (
    "Refusing to build {index}: {count} duplicate ledger_entries group(s) on "
    "(user_id, reason, reference). Resolve them explicitly (refund/void the "
    "extra rows with an audit note), then re-run. Deleting money rows to make "
    "a migration pass is not an acceptable automatic fix."
)


def _inspect() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspect().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(col["name"] == column for col in _inspect().get_columns(table))


def _has_index(table: str, index: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == index for idx in _inspect().get_indexes(table))


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _alter_money_column(table: str, column: str, target: sa.types.TypeEngine[Any]) -> None:
    if not _has_column(table, column):
        return
    if _is_sqlite():
        # SQLite is dynamically typed; there is no ALTER COLUMN TYPE. The
        # declared type is cosmetic there, so the migration leaves it alone.
        return
    op.alter_column(
        table,
        column,
        existing_type=OLD_TYPE if target is MONEY_TYPE else MONEY_TYPE,
        type_=target,
        existing_nullable=None,
        postgresql_using=f"{column}::{target}",
    )


def _duplicate_groups() -> list[tuple[str, str, str, int]]:
    """Keys that would violate the partial unique index, with counts."""
    if not _has_table(LEDGER):
        return []
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT user_id, reason, reference, COUNT(*) AS n "
            "FROM ledger_entries WHERE reference <> '' "
            "GROUP BY user_id, reason, reference HAVING COUNT(*) > 1 "
            "ORDER BY n DESC"
        )
    ).all()
    return [(str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]


def upgrade() -> None:
    # ── 1. FLOAT -> NUMERIC(18,6) ──
    for table, column, _nullable in MONEY_COLUMNS:
        _alter_money_column(table, column, MONEY_TYPE)

    # ── 2. ledger idempotency ──
    duplicates = _duplicate_groups()
    if duplicates and not _has_index(LEDGER, UX_LEDGER):
        raise RuntimeError(UPGRADE_HINT.format(index=UX_LEDGER, count=len(duplicates)))

    if not _has_index(LEDGER, UX_LEDGER):
        op.create_index(
            UX_LEDGER,
            LEDGER,
            ["user_id", "reason", "reference"],
            unique=True,
            sqlite_where=sa.text(_PARTIAL),
            postgresql_where=sa.text(_PARTIAL),
        )

    if not _has_index(LEDGER, IX_LEDGER_REF):
        op.create_index(IX_LEDGER_REF, LEDGER, ["reference"])


def downgrade() -> None:
    """Lossy: NUMERIC(18,6) -> FLOAT can round. Refuses unless acknowledged."""
    if os.environ.get("PRY_ALLOW_LOSSY_DOWNGRADE", "0") != "1":
        raise RuntimeError(
            "0011 downgrade reverts NUMERIC(18,6) money columns to FLOAT, which "
            "is lossy, and drops ledger uniqueness (re-opening double credit). "
            "Set PRY_ALLOW_LOSSY_DOWNGRADE=1 only with a verified backup."
        )

    if _has_index(LEDGER, IX_LEDGER_REF):
        op.drop_index(IX_LEDGER_REF, table_name=LEDGER)
    if _has_index(LEDGER, UX_LEDGER):
        op.drop_index(UX_LEDGER, table_name=LEDGER)

    for table, column, _nullable in MONEY_COLUMNS:
        _alter_money_column(table, column, OLD_TYPE)
