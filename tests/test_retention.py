# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Contract tests for scripts/retention.py (no database required)."""

# ruff: noqa: S608 — asserts on SQL built from fixed policy names
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("pry_retention", ROOT / "scripts" / "retention.py")
retention = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = retention  # dataclasses resolves cls.__module__
_SPEC.loader.exec_module(retention)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        self.conn.executed.append((sql, params))
        if sql.lstrip().upper().startswith("DELETE"):
            self.rowcount = self.conn.delete_rows.pop(0)
        else:
            self.rowcount = 0

    def fetchone(self):
        return (self.conn.expired,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, expired=7, delete_rows=()):
        self.expired = expired
        self.delete_rows = list(delete_rows)
        self.executed = []
        self.commits = 0
        self.autocommit = False

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


@pytest.mark.parametrize("policy", retention.DEFAULT_POLICIES)
def test_delete_sql_targets_table_and_batches(policy):
    sql, params = retention.delete_sql(policy, 250)
    assert sql.startswith(f"DELETE FROM {policy.table} WHERE ctid IN")
    assert f"FROM {policy.table}" in sql
    assert f"{policy.ts_column} < now() - interval %s" in sql
    assert "LIMIT %s" in sql
    assert params == (f"{policy.days} days", 250)


def test_default_windows_are_the_documented_ones():
    windows = {p.table: p.days for p in retention.DEFAULT_POLICIES}
    assert windows == {
        "x402_payment_records": 180,
        "usage": 400,
        "audit_events": 730,
        "scrape_jobs": 30,
    }


def test_count_sql_uses_window():
    policy = retention.DEFAULT_POLICIES[0]
    sql, params = retention.count_sql(policy)
    assert sql.startswith(f"SELECT count(*) FROM {policy.table}")
    assert params == ("180 days",)


def test_batch_size_must_be_positive():
    with pytest.raises(ValueError, match="batch_size"):
        retention.delete_sql(retention.DEFAULT_POLICIES[0], 0)
    with pytest.raises(ValueError, match="days"):
        retention.interval_literal(-1)


def test_dry_run_never_issues_delete():
    conn = _Conn(expired=42, delete_rows=[])
    deleted = retention.purge(conn, retention.DEFAULT_POLICIES[0], batch_size=10, dry_run=True)
    assert deleted == 0
    assert conn.commits == 0
    assert all(not sql.lstrip().upper().startswith("DELETE") for sql, _ in conn.executed)


def test_purge_loops_until_short_batch():
    conn = _Conn(expired=23, delete_rows=[10, 10, 3])
    deleted = retention.purge(conn, retention.DEFAULT_POLICIES[1], batch_size=10)
    assert deleted == 23
    assert conn.commits == 3
    deletes = [p for s, p in conn.executed if s.lstrip().upper().startswith("DELETE")]
    assert deletes == [("400 days", 10)] * 3


def test_stops_immediately_when_nothing_expired():
    conn = _Conn(expired=0, delete_rows=[0])
    assert retention.purge(conn, retention.DEFAULT_POLICIES[3]) == 0
    assert conn.commits == 1


def test_vacuum_runs_analyze_outside_transaction():
    conn = _Conn(expired=1, delete_rows=[1])
    retention.purge(conn, retention.DEFAULT_POLICIES[3], vacuum=True)
    assert conn.autocommit is True
    assert any("VACUUM (ANALYZE) scrape_jobs" in sql for sql, _ in conn.executed)


def test_policy_selection_and_day_overrides():
    selected = retention.select_policies(["x402_payment_records"], ["x402_payment_records=90"])
    assert [(p.table, p.days) for p in selected] == [("x402_payment_records", 90)]
    with pytest.raises(SystemExit):
        retention.select_policies(["not_a_table"])
    with pytest.raises(SystemExit):
        retention.select_policies(None, ["nope=12"])  # unknown table
