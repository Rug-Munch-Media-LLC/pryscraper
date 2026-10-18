"""Regression tests for the async session seam contract.

Contract (one, unambiguous):
- ``get_async_session()`` is a SYNCHRONOUS factory returning ``AsyncSession``.
- ``async_session_scope()`` is an async context manager yielding that session
  and committing on clean exit.

The historical bug: ``async_session_scope`` awaited the factory result, so every
DB-backed request raised ``TypeError: object AsyncSession can't be used in
'await' expression`` (via ``user_ratelimit_quota`` on the MCP auth path).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def async_db(monkeypatch, tmp_path):
    """Point the async engine at a fresh sqlite file and reset cached state."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/scope.db")
    from pry.core.db import db_engine

    monkeypatch.setattr(db_engine, "_async_engine", None)
    monkeypatch.setattr(db_engine, "_async_session_local", None)
    yield tmp_path
    monkeypatch.setattr(db_engine, "_async_engine", None)
    monkeypatch.setattr(db_engine, "_async_session_local", None)


@pytest.mark.asyncio
async def test_get_async_session_is_a_sync_factory(async_db) -> None:
    """The factory returns a session directly; awaiting it is the bug."""
    from pry.core.db import get_async_session

    session = get_async_session()
    try:
        assert isinstance(session, AsyncSession)
        assert not inspect.isawaitable(session)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_async_session_scope_runs_query_and_commits(async_db) -> None:
    """Opening the scope, executing DDL+DML, then exiting must persist rows."""
    from pry.core.db import async_session_scope

    async with async_session_scope() as session:
        assert isinstance(session, AsyncSession)
        await session.execute(text("CREATE TABLE scope_probe (id INTEGER)"))
        await session.execute(text("INSERT INTO scope_probe (id) VALUES (1)"))

    async with async_session_scope() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM scope_probe"))
        assert result.scalar() == 1
        result = await session.execute(text("SELECT 42"))
        assert result.scalar() == 42
