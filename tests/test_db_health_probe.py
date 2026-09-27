# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""A live-but-broken DB connection must not be reported as healthy.

``db_health()`` previously swallowed the SQLite-version probe with a
two-exception clause. Any OperationalError/ProgrammingError — including a dead
connection — came back as ``{"available": True, "sqlite_version": None}``,
byte-identical to a healthy non-SQLite backend, so a broken database passed
the health check.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError

from pry.core.db import migrations

if TYPE_CHECKING:
    from collections.abc import Iterator


def _op_err(msg: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(msg))


@contextmanager
def _health_env(conn: _Conn, url: str) -> Iterator[None]:
    """Bind the engine/URL doubles for the duration of one health call."""
    saved: list[tuple[str, Any]] = []
    for name, value in (
        ("get_engine", lambda: _Engine(conn)),
        ("_resolve_database_url", lambda: url),
    ):
        saved.append((name, getattr(migrations, name)))
        setattr(migrations, name, value)
    try:
        yield
    finally:
        for name, original in saved:
            setattr(migrations, name, original)


class _Result:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _Conn:
    """Connection double. ``select1``/``sqlite`` set each statement's outcome."""

    def __init__(self, select1: Any, sqlite: Any) -> None:
        self._select1 = select1
        self._sqlite = sqlite

    def exec_driver_sql(self, sql: str) -> _Result:
        outcome = self._select1 if sql == "SELECT 1" else self._sqlite
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)


class _ConnCtx:
    """Context manager over a connection double."""

    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def __enter__(self) -> _Conn:
        return self._conn

    def __exit__(self, *a: Any) -> None:
        return None


class _Engine:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def connect(self) -> _ConnCtx:
        return _ConnCtx(self._conn)


def test_db_health_reports_healthy_sqlite() -> None:
    with _health_env(_Conn((1,), ("3.45.0",)), "sqlite:///p.db"):
        assert migrations.db_health() == {
            "available": True,
            "url": "sqlite:///p.db",
            "sqlite_version": "3.45.0",
        }


def test_db_health_non_sqlite_backend_is_available_without_version() -> None:
    """Documented degradation: a healthy Postgres has no sqlite_version()."""
    conn = _Conn((1,), _op_err("no such function: sqlite_version"))
    with _health_env(conn, "postgresql://u:p@h:5432/pry"):
        assert migrations.db_health() == {
            "available": True,
            "url": "h:5432/pry",
            "sqlite_version": None,
        }


def test_db_health_reports_dead_connection_as_unavailable() -> None:
    """A connection that cannot answer SELECT 1 is NOT available."""
    conn = _Conn(_op_err("server closed the connection"), None)
    with _health_env(conn, "sqlite:///p.db"):
        health = migrations.db_health()
    assert health["available"] is False
    assert "server closed the connection" in health["error"]
    assert "sqlite_version" not in health
