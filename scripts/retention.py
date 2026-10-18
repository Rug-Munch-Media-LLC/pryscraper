#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Batched Postgres retention: ctid-batched deletes committed per batch, so no
long transaction or table-wide lock. ``--vacuum`` runs VACUUM (ANALYZE).
"""

# ruff: noqa: S608 — identifiers come from the fixed policy tuple
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

LOG = logging.getLogger("pry.retention")

DEFAULT_BATCH_SIZE = 5_000


@dataclass(frozen=True)
class RetentionPolicy:
    table: str
    ts_column: str
    days: int


DEFAULT_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy("x402_payment_records", "created_at", 180),
    RetentionPolicy("usage", "created_at", 400),
    RetentionPolicy("audit_events", "created_at", 730),
    RetentionPolicy("scrape_jobs", "created_at", 30),
)


def interval_literal(days: int) -> str:
    """Return the Postgres interval literal for a retention window."""
    if days < 0:
        raise ValueError(f"retention days must be >= 0, got {days}")
    return f"{int(days)} days"


def count_sql(policy: RetentionPolicy) -> tuple[str, tuple[Any, ...]]:
    # Identifiers come from the fixed DEFAULT_POLICIES tuple, never from input.
    sql = f"SELECT count(*) FROM {policy.table} WHERE {policy.ts_column} < now() - interval %s"  # nosec B608
    return sql, (interval_literal(policy.days),)


def delete_sql(
    policy: RetentionPolicy, batch_size: int = DEFAULT_BATCH_SIZE
) -> tuple[str, tuple[Any, ...]]:
    """ctid-batched delete: bounded rows, no long-running table scan lock."""
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    # Identifiers come from the fixed DEFAULT_POLICIES tuple, never from input.
    sql = (
        f"DELETE FROM {policy.table} WHERE ctid IN ("  # nosec B608
        f"SELECT ctid FROM {policy.table} "
        f"WHERE {policy.ts_column} < now() - interval %s LIMIT %s)"
    )
    return sql, (interval_literal(policy.days), int(batch_size))


def _log(event: str, **fields: Any) -> None:
    LOG.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def purge(
    conn: Any,
    policy: RetentionPolicy,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    vacuum: bool = False,
) -> int:
    """Delete expired rows in batches. Returns rows deleted (0 on dry-run)."""
    with conn.cursor() as cur:
        cur.execute(*count_sql(policy))
        expired = int(cur.fetchone()[0])

    plan = {"table": policy.table, "ts_column": policy.ts_column, "days": policy.days}
    plan |= {"expired": expired, "batch_size": batch_size, "dry_run": dry_run}
    if dry_run:
        _log("retention.dry_run", **plan)
        return 0

    deleted_total = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(*delete_sql(policy, batch_size))
            deleted = int(cur.rowcount)
        conn.commit()
        deleted_total += deleted
        _log("retention.batch", deleted=deleted, total=deleted_total, **plan)
        if deleted < batch_size:
            break

    if vacuum:
        # VACUUM cannot run inside a transaction block.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"VACUUM (ANALYZE) {policy.table}")
        _log("retention.vacuum", table=policy.table, mode="analyze")
    else:
        hint = f"VACUUM (ANALYZE) {policy.table}"
        _log("retention.vacuum_note", table=policy.table, hint=hint)

    _log("retention.done", deleted=deleted_total, **plan)
    return deleted_total


def _select(tables: Iterable[str] | None) -> list[RetentionPolicy]:
    """Filter the policy table to *tables* (all when empty)."""
    wanted = {t.strip() for t in tables or [] if t.strip()}
    unknown = wanted - {p.table for p in DEFAULT_POLICIES}
    if unknown:
        raise SystemExit(f"unknown table(s): {', '.join(sorted(unknown))}")
    return [p for p in DEFAULT_POLICIES if not wanted or p.table in wanted]


def _apply_overrides(overrides: Iterable[str] | None, by_table: dict[str, RetentionPolicy]) -> None:
    """Apply TABLE=DAYS overrides in place."""
    for raw in overrides or []:
        table, _, days = raw.partition("=")
        if not table or not days:
            raise SystemExit(f"--days expects TABLE=DAYS, got {raw!r}")
        if table not in by_table:
            raise SystemExit(f"--days names an unselected table: {table}")
        by_table[table] = RetentionPolicy(table, by_table[table].ts_column, int(days))


def select_policies(
    tables: Iterable[str] | None = None, overrides: Iterable[str] | None = None
) -> list[RetentionPolicy]:
    """Resolve the retention policy table, filtered and overridden by argv."""
    policies = _select(tables)
    by_table = {p.table: p for p in policies}
    _apply_overrides(overrides, by_table)
    return [by_table[p.table] for p in policies]


def _connect(dsn: str) -> Any:
    import psycopg2  # imported lazily so --help works without the driver

    # pg_dump/psycopg2 accept only libpq schemes; strip SQLAlchemy drivers.
    for prefix in ("postgresql+", "postgres+"):
        if dsn.startswith(prefix):
            dsn = "postgresql://" + dsn.split("://", 1)[1]
            break
    return psycopg2.connect(dsn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pry Postgres retention (batched)")
    parser.add_argument("--dsn", default=os.environ.get("PRY_DATABASE_URL", ""))
    parser.add_argument("--table", action="append", dest="tables", default=[])
    parser.add_argument("--days", action="append", dest="overrides", default=[])
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vacuum", action="store_true", help="VACUUM (ANALYZE) after purge")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.dsn:
        parser.error("--dsn or PRY_DATABASE_URL is required")
    if args.dsn.startswith("sqlite"):
        _log("retention.skipped", reason="sqlite")
        return 0

    policies = select_policies(args.tables, args.overrides)
    conn = _connect(args.dsn)
    try:
        for policy in policies:
            purge(
                conn,
                policy,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                vacuum=args.vacuum,
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
