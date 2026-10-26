"""SQLite storage half of the unlock ledger.

Kept apart from :mod:`pry.engine.unlock_ledger` so both modules stay inside the
repo's 200-line policy — the same split ``method_stats_store`` uses for its
writer. This half owns the schema, redaction and row mapping; the ranking lives
in ``unlock_policy`` and the decision paths in ``unlock_ledger``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pry.engine.unlock_policy import BASELINE_METHODS, MethodRecord

if TYPE_CHECKING:
    from collections.abc import Callable

FLAG_ENV = "PRY_UNLOCK_LEDGER"
DEFAULT_PATH = "~/.pry/unlock_ledger.sqlite3"
# Substrings marking a param key as credential-shaped. The value is never stored.
SECRET_HINTS = (
    "token",
    "key",
    "secret",
    "password",
    "passwd",
    "auth",
    "cookie",
    "session",
    "bearer",
    "sig",
    "credential",
)
REDACTED = "<redacted>"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS unlock_method (
    domain      TEXT NOT NULL,
    method      TEXT NOT NULL,
    params      TEXT NOT NULL DEFAULT '{}',
    selector    TEXT NOT NULL DEFAULT '',
    last_ok_at  REAL,
    ok_count    INTEGER NOT NULL DEFAULT 0,
    fail_count  INTEGER NOT NULL DEFAULT 0,
    fail_streak INTEGER NOT NULL DEFAULT 0,
    latency_ms  REAL NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT '',
    approved    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (domain, method)
)
"""

_UPSERT = """
INSERT INTO unlock_method
    (domain, method, params, selector, last_ok_at, ok_count, fail_count, fail_streak, latency_ms, notes, approved)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(domain, method) DO UPDATE SET
    params      = CASE WHEN excluded.params != '{}' THEN excluded.params ELSE params END,
    selector    = CASE WHEN excluded.selector != '' THEN excluded.selector ELSE selector END,
    notes       = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE notes END,
    last_ok_at  = COALESCE(excluded.last_ok_at, last_ok_at),
    ok_count    = ok_count + excluded.ok_count,
    fail_count  = fail_count + excluded.fail_count,
    fail_streak = CASE WHEN excluded.ok_count > 0 THEN 0 ELSE fail_streak + 1 END,
    latency_ms  = excluded.latency_ms
"""

__all__ = ["FLAG_ENV", "REDACTED", "UnlockStore", "enabled", "normalize_domain", "scrub_params"]


def enabled() -> bool:
    """True when the ledger is wired into crawling (``PRY_UNLOCK_LEDGER=1``)."""
    return os.environ.get(FLAG_ENV, "0").strip().lower() not in ("", "0", "false", "no")


def normalize_domain(domain: str) -> str:
    """Lowercase host without scheme, port, path or a leading ``www.``."""
    host = domain.strip().lower()
    for prefix in ("https://", "http://", "//"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    host = host.split("/")[0].split("?")[0].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def scrub_params(params: dict[str, object] | None) -> dict[str, object]:
    """Redact credential-shaped values. Keys survive so the shape is readable."""
    return {
        k: (REDACTED if any(h in k.lower() for h in SECRET_HINTS) else v)
        for k, v in (params or {}).items()
    }


class UnlockStore:
    """One SQLite handle, one row per ``(domain, method)``."""

    def __init__(self, path: str | None = None, now: Callable[[], float] = time.time) -> None:
        raw = path or os.environ.get("PRY_UNLOCK_LEDGER_PATH") or DEFAULT_PATH
        self._path = raw if raw == ":memory:" else str(Path(raw).expanduser())
        self._now = now
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        """Release the handle."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def records(self, domain: str) -> list[MethodRecord]:
        """Every stored recipe for ``domain``."""
        rows = (
            self._db()
            .execute("SELECT * FROM unlock_method WHERE domain = ?", (normalize_domain(domain),))
            .fetchall()
        )
        return [
            MethodRecord(
                domain=row["domain"],
                method=row["method"],
                params=json.loads(row["params"] or "{}"),
                selector=row["selector"],
                last_ok_at=row["last_ok_at"],
                ok_count=row["ok_count"],
                fail_count=row["fail_count"],
                fail_streak=row["fail_streak"],
                latency_ms=row["latency_ms"],
                notes=row["notes"],
                approved=bool(row["approved"]),
            )
            for row in rows
        ]

    def record_result(
        self,
        domain: str,
        method: str,
        ok: bool,
        latency_ms: float = 0.0,
        params: dict[str, object] | None = None,
        selector: str = "",
        notes: str = "",
    ) -> None:
        """Remember one outcome. A success resets the failure streak."""
        approved = 1 if method in BASELINE_METHODS else 0
        self._db().execute(
            _UPSERT,
            (
                normalize_domain(domain),
                method,
                json.dumps(scrub_params(params), sort_keys=True),
                selector,
                self._now() if ok else None,
                1 if ok else 0,
                0 if ok else 1,
                0 if ok else 1,
                max(float(latency_ms), 0.0),
                notes,
                approved,
            ),
        )
        self._db().commit()

    def approve(self, domain: str, method: str) -> bool:
        """Human gate: allow replay of a discovered method. False if unknown."""
        cursor = self._db().execute(
            "UPDATE unlock_method SET approved = 1 WHERE domain = ? AND method = ?",
            (normalize_domain(domain), method),
        )
        self._db().commit()
        return cursor.rowcount > 0
