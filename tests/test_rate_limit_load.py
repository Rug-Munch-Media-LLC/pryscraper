"""Pre-auth limiter under load: boundary, Retry-After, no work after 429.

Drives one IP past its token bucket through the real middleware, proving the
429 is the boundary (not later), that authentication/DB work stops at the
limit, that X-Forwarded-For cannot select the bucket, and that another IP is
unaffected. Also measures the limiter's own per-check cost so the ceiling is
not the bottleneck.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.core import middleware as facade, middleware_ratelimit as rl
from pry.core.middleware import PryHttpMiddleware

CLIENT = "203.0.113.60"
OTHER = "203.0.113.61"
SPOOF = "198.51.100.9"


@pytest.fixture(autouse=True)
def _fresh_buckets():
    rl._PREAUTH_BUCKETS.clear()
    yield
    rl._PREAUTH_BUCKETS.clear()


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(PryHttpMiddleware)
    return app


def _client(ip: str = CLIENT) -> TestClient:
    return TestClient(_app(), client=(ip, 4000))


def _limit() -> int:
    """Anonymous per-IP ceiling as the limiter computes it (>= 60)."""
    return rl._preauth_rules(False)[0]


def _deny(monkeypatch) -> list[int]:
    """Spy on credential resolution: records each auth attempt, always denies."""
    calls: list[int] = []

    def _request_authorized(scope):
        calls.append(1)
        return False

    monkeypatch.setattr(facade, "request_authorized", _request_authorized)
    return calls


def _frozen_clock(monkeypatch) -> None:
    """Freeze monotonic time so token refill cannot reopen the bucket."""
    monkeypatch.setattr(rl.time, "monotonic", lambda: 1000.0)


def test_429_is_the_exact_boundary_and_no_auth_runs_after_it(monkeypatch):
    calls = _deny(monkeypatch)
    _frozen_clock(monkeypatch)
    client, limit = _client(), _limit()

    allowed = [client.get("/v1/scrape").status_code for _ in range(limit)]
    assert set(allowed) == {401}
    assert len(calls) == limit

    blocked = client.get("/v1/scrape")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # The 429 short-circuits before credential resolution / DB lookup.
    assert len(calls) == limit

    for _ in range(5):
        assert client.get("/v1/scrape").status_code == 429
    assert len(calls) == limit


def test_spoofed_xff_from_untrusted_peer_cannot_change_bucket(monkeypatch):
    _deny(monkeypatch)
    _frozen_clock(monkeypatch)
    client = _client()
    for _ in range(_limit()):
        client.get("/v1/scrape")

    spoofed = client.get("/v1/scrape", headers={"X-Forwarded-For": SPOOF})
    assert spoofed.status_code == 429
    # The spoof address still has its own untouched bucket.
    assert _client(SPOOF).get("/v1/scrape").status_code == 401


def test_a_different_ip_is_unaffected(monkeypatch):
    _deny(monkeypatch)
    _frozen_clock(monkeypatch)
    client = _client()
    for _ in range(_limit()):
        client.get("/v1/scrape")
    assert client.get("/v1/scrape").status_code == 429
    assert _client(OTHER).get("/v1/scrape").status_code == 401


def test_429_path_throughput(monkeypatch):
    _deny(monkeypatch)
    client = _client()
    rl._PREAUTH_BUCKETS[f"{CLIENT}|anon"] = [-10.0, time.monotonic()]
    rounds = 300
    started = time.perf_counter()
    for _ in range(rounds):
        assert client.get("/v1/scrape").status_code == 429
    elapsed = time.perf_counter() - started
    rps = rounds / elapsed
    # TestClient + structured logging dominate; the limiter itself is measured
    # separately in test_limiter_check_cost_is_not_a_bottleneck.
    assert rps > 20, f"limiter path too slow: {rps:.1f} req/s"


def test_limiter_check_cost_is_not_a_bottleneck():
    rl._PREAUTH_BUCKETS.clear()
    calls = 100_000
    started = time.perf_counter()
    for _ in range(calls):
        rl.preauth_check(CLIENT)
    per_call_us = (time.perf_counter() - started) / calls * 1e6
    assert per_call_us < 100, f"limiter check too expensive: {per_call_us:.1f} us"


def test_bucket_table_is_bounded_under_many_client_ips():
    for i in range(rl._PREAUTH_MAX_KEYS + 20):
        rl.preauth_check(f"10.{(i >> 8) & 255}.{i & 255}.1")
    assert len(rl._PREAUTH_BUCKETS) <= rl._PREAUTH_MAX_KEYS
