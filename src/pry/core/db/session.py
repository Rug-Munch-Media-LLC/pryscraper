"""Pry - engine setup and session factories (compatibility facade).

Engine construction/state moved to ``db_engine``; schema bootstrap and the
session factory helpers moved to ``db_init``. Every previously public name is
re-exported here, so ``from pry.core.db.session import X`` is unchanged.

The module-level ``_engine`` / ``_SessionLocal`` state is the single source of
truth in ``db_engine``; this module forwards reads and the top-level ``db``
package forwards writes, so ``db._engine = None`` (used by tests to force
engine recreation) keeps working unchanged.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pry.core.db import db_engine
from pry.core.db.db_engine import (
    DATABASE_URL_ENV,
    DEFAULT_DB_PATH,
    DEFAULT_PG_URL,
    DEFAULT_SQLITE_URL,
    _engine_lock,
    _has_sqlalchemy,
    _profile,
    _resolve_async_database_url,
    _resolve_database_url,
    dispose_engines,
    get_async_engine,
    get_db,
    get_engine,
)
from pry.core.db.db_init import (
    async_session_scope,
    get_async_session,
    get_session,
    init_db,
    session_scope,
)

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_DB_PATH",
    "DEFAULT_PG_URL",
    "DEFAULT_SQLITE_URL",
    "_engine_lock",
    "_has_sqlalchemy",
    "_profile",
    "_resolve_async_database_url",
    "_resolve_database_url",
    "async_session_scope",
    "dispose_engines",
    "get_async_engine",
    "get_async_session",
    "get_db",
    "get_engine",
    "get_session",
    "init_db",
    "session_scope",
]

_STATE_NAMES = ("_engine", "_SessionLocal", "_async_engine", "_async_session_local")


def __getattr__(name: str) -> Any:
    """Forward engine-state reads to ``db_engine`` (PEP 562)."""
    if name in _STATE_NAMES:
        return getattr(db_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_STATE_NAMES))
