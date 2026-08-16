"""Pry - SQLAlchemy database foundation (package).

Splits the legacy monolithic ``db.py`` into focused submodules while
preserving the public import surface: every name that was previously
importable from ``db`` is re-exported here, so ``from db import X`` keeps
working unchanged (e.g. ``session_scope``, all ORM models, ``Base``,
``get_engine``, ``run_migrations``, ``db_health``, ...).

Module layout:
    db.session       - engine setup + sync/async session factories
    db.models        - DeclarativeBase + the 15 ORM models
    db.import_json   - one-shot JSON store importer
    db.migrations    - Alembic runner + health helpers

Why migrate:
  - JSON files give no concurrency control. Two writes = corruption.
  - No transactions. A partial write is permanent.
  - No querying. Can't ask "all monitors on example.com".
  - No relationships. Can't join a monitor with its alerts.

Engine selection:
  - Default: SQLite at $PRY_DATA_DIR/pry.db. Zero-config, file-based.
  - Production: set PRY_DATABASE_URL=postgresql://... to use Postgres.
    SQLAlchemy handles the rest; no code changes.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import sys
import types
from typing import Any

from . import session as _session
from .import_json import import_json_stores
from .migrations import db_health, db_health_async, run_migrations
from .models import (
    Account,
    Actor,
    Agency,
    Base,
    BrowserSession,
    IntelSnapshot,
    Monitor,
    MonitorRun,
    Pipeline,
    QualityCheck,
    ReferralClick,
    ReferralConversion,
    ReferralInAppUsage,
    Report,
    StructureSnapshot,
    Webhook,
)
from .session import (
    DATABASE_URL_ENV,
    DEFAULT_DB_PATH,
    DEFAULT_SQLITE_URL,
    _has_sqlalchemy,
    _resolve_async_database_url,
    _resolve_database_url,
    async_session_scope,
    dispose_engines,
    get_async_engine,
    get_async_session,
    get_db,
    get_engine,
    get_session,
    session_scope,
)

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_DB_PATH",
    "DEFAULT_SQLITE_URL",
    "Account",
    "Actor",
    "Agency",
    "Base",
    "BrowserSession",
    "IntelSnapshot",
    "Monitor",
    "MonitorRun",
    "Pipeline",
    "QualityCheck",
    "ReferralClick",
    "ReferralConversion",
    "ReferralInAppUsage",
    "Report",
    "StructureSnapshot",
    "Webhook",
    "_has_sqlalchemy",
    "_resolve_async_database_url",
    "_resolve_database_url",
    "async_session_scope",
    "db_health",
    "db_health_async",
    "dispose_engines",
    "get_async_engine",
    "get_async_session",
    "get_db",
    "get_engine",
    "get_session",
    "import_json_stores",
    "run_migrations",
    "session_scope",
]


# ── Engine/session state write-through ─────────────────────────────
#
# Tests (and a few call sites) manipulate the module-level engine state
# directly: ``db._engine = None`` / ``db._SessionLocal = None`` to force a
# fresh engine for an isolated test database. The real state lives in
# ``db.session``; this module type transparently routes attribute reads
# and writes there, so those assignments keep their original semantics.
class _DbModuleType(types.ModuleType):
    @property
    def _engine(self) -> Any:
        return _session._engine

    @_engine.setter
    def _engine(self, value: Any) -> None:
        _session._engine = value

    @property
    def _SessionLocal(self) -> Any:  # noqa: N802 - mirrors db._SessionLocal state name
        return _session._SessionLocal

    @_SessionLocal.setter
    def _SessionLocal(self, value: Any) -> None:  # noqa: N802
        _session._SessionLocal = value

    @property
    def _async_engine(self) -> Any:
        return _session._async_engine

    @_async_engine.setter
    def _async_engine(self, value: Any) -> None:
        _session._async_engine = value

    @property
    def _async_session_local(self) -> Any:
        return _session._async_session_local

    @_async_session_local.setter
    def _async_session_local(self, value: Any) -> None:
        _session._async_session_local = value


sys.modules[__name__].__class__ = _DbModuleType  # type: ignore[misc]
