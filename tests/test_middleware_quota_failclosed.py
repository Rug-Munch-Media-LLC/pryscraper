"""The quota gate must be reachable from a REAL request, not just a unit test.

Commit fe793ce0 made the limiter fail-closed (a failed quota read raises
QuotaUnavailableError, marks the bucket unverified, and check() denies) but
nothing on the HTTP path ever called ``_sync_quota`` — the deny was dead code,
so a database outage still served every request at quota_used=0.

These tests drive the real PryHttpMiddleware with the real UserRateLimiter and
a broken database, and assert the request is denied.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import asyncio
import json
import time

import pytest
from sqlalchemy.exc import OperationalError

from pry.core import middleware as mw, user_ratelimit as user_ratelimit_mod
from pry.core.middleware_http import PryHttpMiddleware
from pry.core.user_ratelimit import UserRateLimiter

# Non-secret test key: the middleware only requires a Bearer value that
# differs from settings.api_key. Kept obviously fake so no scanner flags it.
DB_KEY = "pry_test_key_00000000"


def _real_app(deny_sentinel: bool = True):
    """A minimal Starlette app with one routed path, so the middleware
    reaches the rate-limit branch instead of the unknown-path passthrough.

    ``deny_sentinel`` makes any downstream call an AssertionError, which is
    how the denial tests prove a blocked request never reaches the app.
    """
    from starlette.routing import Route

    async def _endpoint():
        return {"ok": True}

    class App:
        """Routes are what the middleware path-matcher checks; the call is a
        sentinel that fails the test if a DENIED request ever reaches it."""

        def __init__(self):
            self.routes = [Route("/v1/scrape", _endpoint)]

        async def __call__(self, scope, receive, send):
            if deny_sentinel:
                raise AssertionError("downstream must not see a denied request")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

    return App()


def _scope():
    return {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [(b"authorization", f"Bearer {DB_KEY}".encode())],
        "client": ("203.0.113.9", 5),
        "query_string": b"",
    }


@pytest.fixture
def db_down(monkeypatch):
    """Make every quota read fail the way a real DB outage does."""

    def _scope_cm():
        db_error = OperationalError("SELECT sum(cost_usd)...", {}, Exception("down"))

        class _FailingSession:
            async def __aenter__(self):
                raise db_error

            async def __aexit__(self, *exc):
                return False

        return _FailingSession()

    monkeypatch.setattr(user_ratelimit_mod, "async_session_scope", _scope_cm)
    return _scope_cm


def _run(monkeypatch, limiter: UserRateLimiter, *, deny_sentinel: bool = True) -> list[dict]:
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    monkeypatch.setattr(mw, "user_ratelimiter", limiter)
    monkeypatch.setattr(mw, "request_authorized", lambda *a, **k: True)
    app = _real_app(deny_sentinel)
    asyncio.run(PryHttpMiddleware(app=app)(_scope(), receive, send))
    return sent


def test_db_outage_during_real_request_is_denied(monkeypatch, db_down):
    """A DB error during a real request must produce a 429, not a 200.

    This is the regression test for the dead gate: before the refresh was
    wired in, no quota read happened on the request path, quota_used stayed
    0.0 and the request was ALLOWED during a full database outage.
    """
    limiter = UserRateLimiter()
    sent = _run(monkeypatch, limiter)

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 429, "fail-closed: a DB outage must deny"
    body = json.loads(sent[1]["body"])
    assert body["code"] == "rate_limit_exceeded"


def test_db_outage_never_reports_zero_usage(monkeypatch, db_down):
    """The denial must not leak a fabricated quota_used=0 to the client —
    that number is what made a DB outage look like an unlimited user."""
    limiter = UserRateLimiter()
    sent = _run(monkeypatch, limiter)

    assert dict(sent[0]["headers"]).get(b"x-ratelimit-quota-used") is None


def test_fresh_quota_is_served_from_cache(monkeypatch, db_down):
    """Within the TTL the cached quota is used — no DB hit per request."""
    limiter = UserRateLimiter()
    _run(monkeypatch, limiter)
    assert limiter.get_bucket(DB_KEY[:12]).quota_unverified is True

    calls = []

    async def _load(api_key_id):
        calls.append(api_key_id)
        return 0.0

    monkeypatch.setattr(limiter, "_load_quota_from_db", _load)
    bucket = limiter.get_bucket(DB_KEY[:12])
    bucket.quota_synced_at = time.time()
    asyncio.run(limiter.refresh_quota(DB_KEY[:12]))
    assert calls == [], "a fresh bucket must not hit the database"
    # Still unverified: the cache TTL suppresses the retry, not the denial.
    assert bucket.quota_unverified is True


def test_successful_read_clears_unverified_and_uncovers_the_request(monkeypatch, db_down):
    """The recovery direction: once the DB is back the request is served and
    the unverified flag clears, so the gate is not a permanent lockout."""
    limiter = UserRateLimiter()
    _run(monkeypatch, limiter)  # DB down: 429, bucket ends up unverified
    assert limiter.get_bucket(DB_KEY[:12]).quota_unverified is True

    class _WorkingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, _stmt):
            class _Result:
                def scalar(self):
                    return 12.0

            return _Result()

    monkeypatch.setattr(
        user_ratelimit_mod,
        "async_session_scope",
        lambda: _WorkingSession(),
    )
    sent = _run(monkeypatch, limiter, deny_sentinel=False)

    assert sent[0]["status"] == 200, "a recovered DB must serve the request"
    bucket = limiter.get_bucket(DB_KEY[:12])
    assert bucket.quota_unverified is False
    assert bucket.quota_used == 12.0, "the recovered read must be enforced, not 0"
