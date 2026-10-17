# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Integration tests for existing modules that require live infrastructure.

These tests are marked ``integration`` and are DESELECTED from the default
run (pyproject addopts ``-m 'not integration'``). They run only in the
nightly Forgejo job (``.forgejo/workflows/ci.yml`` → ``integration-nightly``)
which starts ephemeral postgres:16 + redis:7 containers and sets
``PRY_DATABASE_URL`` / ``PRY_REDIS_URL``.

Run locally with:
    docker run -d --name pry-pg -e POSTGRES_USER=pry -e POSTGRES_PASSWORD=pry \
        -e POSTGRES_DB=pry -p 5432:5432 postgres:16-alpine
    docker run -d --name pry-redis -p 6379:6379 redis:7-alpine
    PRY_DATABASE_URL=postgresql://pry:pry@localhost:5432/pry \
        PRY_REDIS_URL=redis://localhost:6379/0 \
        pytest -m integration
"""

from __future__ import annotations

import importlib
import os
import uuid

import pytest

import pry.core.paths as paths

pytestmark = pytest.mark.integration


def _sync_database_url() -> str:
    """Return a sync-driver Postgres URL for session_scope tests.

    The nightly job sets ``PRY_DATABASE_URL`` to an asyncpg URL (async
    engine). ``session_scope()`` uses the SYNC engine, so the asyncpg driver
    must be swapped for psycopg2 here. Falls back to localhost defaults for
    local ``pytest -m integration`` runs.
    """
    url = os.environ.get(
        "PRY_DATABASE_URL",
        "postgresql://pry:pry@localhost:5432/pry",
    )
    return (
        url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        if url.startswith("postgresql+asyncpg://")
        else url
    )


def _redis_url() -> str:
    return os.environ.get("PRY_REDIS_URL", "redis://localhost:6379/0")


def _database_reachable() -> bool:
    """Probe the DB with a real connection; True when reachable with creds."""
    from sqlalchemy import create_engine

    try:
        eng = create_engine(_sync_database_url(), connect_args={"connect_timeout": 3})
        with eng.connect():
            return True
    except Exception:  # noqa: BLE001 - any failure means "skip the test"
        return False
    finally:
        if "eng" in locals():
            eng.dispose()


# ── db.session_scope roundtrip ────────────────────────────────────


@pytest.fixture
def postgres_engine():
    """Point the db package at Postgres and reset its cached engine."""
    if not _database_reachable():
        pytest.skip("Postgres not reachable with PRY_DATABASE_URL")

    import pry.core.db as db

    old_db_url = os.environ.get("PRY_DATABASE_URL")
    os.environ["PRY_DATABASE_URL"] = _sync_database_url()
    try:
        importlib.reload(paths)
        db._engine = None
        db._SessionLocal = None
        db._async_engine = None
        db._async_session_local = None
        yield db
    finally:
        db._engine = None
        db._SessionLocal = None
        db._async_engine = None
        db._async_session_local = None
        if old_db_url is None:
            os.environ.pop("PRY_DATABASE_URL", None)
        else:
            os.environ["PRY_DATABASE_URL"] = old_db_url


def test_session_scope_postgres_roundtrip(postgres_engine) -> None:
    """session_scope() must commit a row that a fresh session can read back.

    Verifies the write path (add + commit on clean exit) and the read path
    (query in a new session) against a real Postgres, exercising the exact
    context manager used by production endpoints.
    """
    from sqlalchemy import select

    from pry.core.db.models import Account

    account_id = f"it-{uuid.uuid4().hex[:16]}"
    service = "integration-test"

    # Write via session_scope: commit happens on clean exit.
    with postgres_engine.session_scope() as s:
        s.add(
            Account(
                account_id=account_id,
                service=service,
                username="integration-bot",
                email="it@example.com",
                status="active",
                used_count=0,
            )
        )

    # Read back in a fresh session (new connection, new transaction).
    with postgres_engine.session_scope() as s:
        row = s.execute(select(Account).where(Account.account_id == account_id)).scalar_one()

    assert row.account_id == account_id
    assert row.service == service
    assert row.username == "integration-bot"
    assert row.status == "active"

    # Cleanup: remove the row so reruns stay idempotent.
    with postgres_engine.session_scope() as s:
        s.execute(Account.__table__.delete().where(Account.account_id == account_id))


def test_session_scope_rolls_back_on_error(postgres_engine) -> None:
    """session_scope() must roll back when the body raises — nothing persists."""
    from sqlalchemy import select

    from pry.core.db.models import Account

    account_id = f"it-rollback-{uuid.uuid4().hex[:16]}"

    with pytest.raises(RuntimeError), postgres_engine.session_scope() as s:
        s.add(
            Account(
                account_id=account_id,
                service="integration-test",
                username="will-rollback",
                status="active",
            )
        )
        raise RuntimeError("boom")

    # The failed transaction must NOT have been committed.
    with postgres_engine.session_scope() as s:
        count = (
            s.execute(select(Account.id).where(Account.account_id == account_id)).scalars().all()
        )
    assert count == []


# ── JobQueue Redis persistence ─────────────────────────────────────


@pytest.fixture
def redis_client():
    """Redis client for direct assertions; skips when Redis is unreachable."""
    import redis.asyncio as aioredis

    async def _make():
        client = await aioredis.from_url(_redis_url(), socket_timeout=2)
        try:
            await client.ping()
        except Exception:  # noqa: BLE001 - any failure means "skip the test"
            await client.aclose()
            pytest.skip(f"Redis not reachable at {_redis_url()}")
        return client

    return _make


@pytest.mark.asyncio
async def test_jobqueue_persists_jobs_in_redis(redis_client) -> None:
    """JobQueue must persist jobs in Redis — a NEW instance reads them back.

    The default-run unit tests exercise the in-memory fallback only. This
    test verifies the Redis path: a job created by one JobQueue instance is
    readable by a brand-new instance (proving it lives in Redis, not in the
    first instance's local store).
    """
    import json

    from pry.core.jobqueue import JobQueue

    redis = await redis_client()

    q1 = JobQueue(redis_url=_redis_url())
    job_id = await q1.create_job("integration", {"url": "https://example.com"})

    try:
        # The raw Redis key must exist.
        raw = await redis.get(f"pry:job:{job_id}")
        assert raw is not None, "job not found in Redis"
        job = json.loads(raw)
        assert job["id"] == job_id
        assert job["type"] == "integration"
        assert job["status"] == "pending"

        # A brand-new JobQueue (empty local store) must still see the job.
        q2 = JobQueue(redis_url=_redis_url())
        assert q2._local_jobs == {}
        reloaded = await q2.get_job(job_id)
        assert reloaded is not None
        assert reloaded["id"] == job_id
        assert reloaded["type"] == "integration"
    finally:
        await redis.delete(f"pry:job:{job_id}")
        await redis.aclose()


@pytest.mark.asyncio
async def test_jobqueue_complete_updates_redis(redis_client) -> None:
    """complete_job() must update the Redis-persisted job, not just memory."""
    import json

    from pry.core.jobqueue import JobQueue

    redis = await redis_client()

    q = JobQueue(redis_url=_redis_url())
    job_id = await q.create_job("integration", {"url": "https://example.com"})

    try:
        await q.complete_job(job_id, {"ok": True})

        raw = await redis.get(f"pry:job:{job_id}")
        assert raw is not None
        job = json.loads(raw)
        assert job["status"] == "completed"
        expected = {"ok": True}
        assert job["result"] == expected
    finally:
        await redis.delete(f"pry:job:{job_id}")
        await redis.aclose()
