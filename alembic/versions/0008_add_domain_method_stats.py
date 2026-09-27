"""add domain_method_stats — durable home for the learned per-domain method memory

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27 00:00:00.000000

Aggregate (not event-log) table: one row per (domain, method) holding running
counters, so the write path can upsert and the read path can rank without
aggregating. `attempts - wins` is the failure count.

`latency_p50_ms` / `latency_p95_ms` are milliseconds (the in-process record
keeps total latency in seconds; the p50/p95 split is only meaningful per
sample, so it is computed by the writer from the sample batch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "domain_method_stats"
# Hot read path: "which methods have worked on this domain, best first".
IX_DOMAIN_WINS = "ix_domain_method_stats_domain_wins"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_p50_ms", sa.Float(), server_default="0", nullable=False),
        sa.Column("latency_p95_ms", sa.Float(), server_default="0", nullable=False),
        sa.Column("cost_usd_total", sa.Float(), server_default="0", nullable=False),
        sa.Column("last_block_kind", sa.String(32), server_default="", nullable=False),
        # Unix seconds. The in-process record already carries float epoch
        # timestamps, so storing epoch avoids a UTC-naive/aware round trip on
        # every read. Kept as a plain integer so both the Postgres and the
        # SQLite (test) backends agree exactly.
        sa.Column("last_seen_at", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("domain", "method", name="pk_domain_method_stats"),
    )
    op.create_index(IX_DOMAIN_WINS, TABLE, ["domain", "wins"])


def downgrade() -> None:
    op.drop_index(IX_DOMAIN_WINS, table_name=TABLE)
    op.drop_table(TABLE)
