"""Pry - schema bootstrap and sync/async session factories.

Engine state lives in ``db_engine``; helpers here read it dynamically so the
documented ``db._engine = None`` reset keeps forcing fresh engines.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

from pry.core.db import db_engine
from pry.core.db.db_engine import get_async_engine, get_engine
from pry.core.db.models import Base

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Cold-start / test helper: create all tables from the models.

    NOT the schema authority — ``alembic upgrade head`` is. Called once from
    the FastAPI lifespan; set ``PRY_ALEMBIC_AUTO=0`` to skip it entirely
    (production deploys do). Keeping it out of ``get_engine()`` is what stops
    the per-process schema drift.
    """
    if os.environ.get("PRY_ALEMBIC_AUTO", "1") == "0":
        return
    Base.metadata.create_all(get_engine())


def get_session() -> Session:
    """Get a new Session. Caller is responsible for closing it."""
    # Guard BOTH cached handles: tests reset the engine via the documented
    # ``db._engine = None`` pattern. If only _engine is cleared, a stale
    # _SessionLocal would keep handing out sessions bound to the dead engine
    # (deleted tmp sqlite -> "no such table" errors).
    if db_engine._SessionLocal is None or db_engine._engine is None:
        get_engine()
    assert db_engine._SessionLocal is not None
    return db_engine._SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager: yields a Session, commits on success, rolls back on error."""
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_async_session() -> AsyncSession:
    """Get a new async Session. Caller must close it."""
    if db_engine._async_session_local is None:
        get_async_engine()
    assert db_engine._async_session_local is not None
    return db_engine._async_session_local()


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Async context manager: commits on success, rolls back on error."""
    s = await get_async_session()
    try:
        yield s
        await s.commit()
    except Exception:
        await s.rollback()
        raise
    finally:
        await s.close()
