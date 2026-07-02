# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for production infrastructure (auth, db, observability, jobs)."""

import asyncio

from auth import AuthManager, base64_decode, base64_encode
from db import _has_sqlalchemy, get_db
from observability import track_llm_call, track_request, track_scrape
from tasks import JobQueue, JobStatus


def test_auth_hash_password() -> None:
    a = AuthManager()
    h, salt = a.hash_password("hunter2")
    assert a.verify_password("hunter2", h, salt) is True
    assert a.verify_password("wrong", h, salt) is False


def test_auth_api_key() -> None:
    a = AuthManager()
    user = a.create_user("test@example.com", "password")
    key = a.create_api_key(user["id"])
    assert key.startswith("pry_")
    verified = a.verify_api_key(key)
    assert verified is not None
    assert verified["user_id"] == user["id"]
    # Invalid key
    assert a.verify_api_key("invalid") is None


def test_auth_rate_limit() -> None:
    a = AuthManager()
    a._rate_limits["test"] = {"window_start": 0, "count": 0}
    allowed, remaining = a.check_rate_limit("test")
    assert allowed is True
    assert remaining >= 0


def test_auth_jwt_fallback() -> None:
    a = AuthManager()
    user = a.create_user("jwt@test.com", "pass")
    token = a.create_jwt(user["id"])
    payload = a.verify_jwt(token)
    assert payload is not None
    assert payload["sub"] == user["id"]


def test_base64_roundtrip() -> None:
    assert base64_decode(base64_encode("hello world")) == "hello world"


def test_observability_track_request() -> None:
    with track_request("/test"):
        pass  # Should not raise


def test_observability_track_scrape() -> None:
    with track_scrape("direct"):
        pass


def test_observability_track_llm() -> None:
    track_llm_call("openai", "gpt-4o-mini", 0.001)


def test_db_is_available() -> None:
    # Just check it doesn't crash; may be unavailable if no sqlalchemy
    db = get_db()
    if _has_sqlalchemy:
        assert db is not None


def test_job_queue_submit() -> None:
    async def _test():
        q = JobQueue()

        async def my_task(x):
            return x * 2

        job_id = await q.submit("double", my_task, args=(5,))
        assert job_id in q.jobs
        # Run inline
        job = q.jobs[job_id]
        await q._execute(job)
        assert job.status == JobStatus.COMPLETED
        assert job.result == 10

    asyncio.run(_test())


def test_job_listing() -> None:
    q = JobQueue()
    q.jobs["test"] = type("J", (), {"to_dict": lambda self: {"id": "test", "name": "x"}})()
    # Simple smoke test
    assert hasattr(q, "list_jobs")
