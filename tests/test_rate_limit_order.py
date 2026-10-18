"""Rate-limit ordering: pre-auth IP ceiling, client-IP trust, Redis-down policy.

Pins three fixed defects: the limiter ran AFTER auth (so garbage keys cost a
DB lookup), keyless floods were only limited per-route (unknown paths bypassed
the limiter), and the limiter's IP could be taken from a spoofed
``X-Forwarded-For``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from pry.core import middleware as facade, middleware_ratelimit as rl
from pry.core.middleware import PryHttpMiddleware

ORIGIN = "https://pryscraper.com"
SPOOF = "198.51.100.7"
FAIL_OPEN = "pry_rate_limit_fail_open_total"


@pytest.fixture(autouse=True)
def _fresh_buckets():
    """Each test starts with empty pre-auth buckets (module-level state)."""
    rl._PREAUTH_BUCKETS.clear()
    yield
    rl._PREAUTH_BUCKETS.clear()


def _app(*, cors: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(PryHttpMiddleware)
    if cors:
        # Added LAST => outermost, so the direct-send 429 is CORS-readable
        # (mirrors app_wiring.wire_app's ordering).
        app.add_middleware(
            CORSMiddleware, allow_origins=[ORIGIN], allow_methods=["*"], allow_headers=["*"]
        )
    return app


def _drain(ip: str, *, credential_present: bool = False) -> None:
    """Exhaust the matching pre-auth bucket for ``ip`` (no tokens left)."""
    tag = "cred" if credential_present else "anon"
    rl._PREAUTH_BUCKETS[f"{ip}|{tag}"] = [0.0, time.monotonic()]


def _deny(monkeypatch) -> list[int]:
    """Replace credential resolution with a spy that records and denies."""
    calls: list[int] = []

    def _request_authorized(scope):
        calls.append(1)
        return False

    monkeypatch.setattr(facade, "request_authorized", _request_authorized)
    return calls


def test_anonymous_flood_429_before_any_key_lookup(monkeypatch):
    calls = _deny(monkeypatch)
    _drain("203.0.113.5", credential_present=True)
    client = TestClient(_app(), client=("203.0.113.5", 4000))
    resp = client.get("/v1/scrape", headers={"Authorization": "Bearer pry_garbage"})
    assert resp.status_code == 429
    assert calls == []  # auth (and its DB lookup) never ran
    assert int(resp.headers["retry-after"]) >= 1
    # Anonymous traffic from the same IP has its own (still full) bucket.
    assert client.get("/v1/scrape").status_code == 401


def test_spoofed_xff_from_untrusted_peer_keeps_peer_bucket(monkeypatch):
    _deny(monkeypatch)
    _drain("203.0.113.9")
    spoofed = TestClient(_app(), client=("203.0.113.9", 4000))
    assert spoofed.get("/v1/scrape", headers={"X-Forwarded-For": SPOOF}).status_code == 429
    # The spoof target's bucket was NOT touched: a direct request from that
    # IP still reaches auth (401) instead of inheriting the drained bucket.
    other = TestClient(_app(), client=(SPOOF, 4000))
    assert other.get("/v1/scrape").status_code == 401


def test_trusted_proxy_honours_xff_hop(monkeypatch):
    _deny(monkeypatch)
    monkeypatch.setattr(facade, "_is_trusted_proxy", lambda ip: ip == "10.1.2.3")
    _drain(SPOOF)
    proxied = TestClient(_app(), client=("10.1.2.3", 4000))
    assert proxied.get("/v1/scrape", headers={"X-Forwarded-For": SPOOF}).status_code == 429
    # A different forwarded client is a different bucket.
    fresh = TestClient(_app(), client=("10.1.2.3", 4000))
    assert fresh.get("/v1/scrape", headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 401


def test_429_is_cors_readable_and_has_retry_after(monkeypatch):
    _deny(monkeypatch)
    _drain("203.0.113.11")
    resp = TestClient(_app(cors=True), client=("203.0.113.11", 4000)).get(
        "/v1/scrape", headers={"Origin": ORIGIN}
    )
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert "retry-after" in resp.headers


class _FakeLimiter:
    """Legacy IP limiter double: ``backend`` drives the fail-open metric."""

    default_rpm = 120

    def __init__(self, backend: str = "memory"):
        self.backend = backend

    def check(self, ip, rpm=None):
        return True, {"remaining": 1, "limit": self.default_rpm}


def _scope(headers=None, key=None):
    return {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": headers or [],
        "pry_api_key": key,
    }


def _sample() -> float:
    return REGISTRY.get_sample_value(FAIL_OPEN, {"backend": "memory"}) or 0


def test_redis_down_fails_open_with_metric(monkeypatch):
    monkeypatch.setattr(facade, "ratelimiter", _FakeLimiter("memory"))
    monkeypatch.setattr(rl.settings, "redis_url", "redis://configured")
    before = _sample()
    allowed, stats, headers, _ = asyncio.run(rl.resolve_rate_limit(_scope(), "1.2.3.4"))
    assert allowed
    assert stats["limit"] == 120
    assert headers["x-ratelimit-limit"] == "120"
    assert _sample() == before + 1  # degradation is counted, not silent


def test_redis_up_is_not_counted_as_fail_open(monkeypatch):
    monkeypatch.setattr(facade, "ratelimiter", _FakeLimiter("redis"))
    monkeypatch.setattr(rl.settings, "redis_url", "redis://configured")
    before = _sample()
    allowed, _, _, _ = asyncio.run(rl.resolve_rate_limit(_scope(), "1.2.3.4"))
    assert allowed
    assert _sample() == before


class _FakeUserLimiter:
    """Per-key limiter double that records the refresh and denies the check."""

    def __init__(self):
        self.refreshed: list[str] = []
        self.checked: list[str] = []

    async def refresh_quota(self, bucket_id):
        self.refreshed.append(bucket_id)

    def check(self, *, api_key_id, tier, rpm, quota_monthly, cost_usd):
        self.checked.append(api_key_id)
        return False, {
            "reason": "monthly quota exceeded",
            "retry_after": 30,
            "limit": rpm or 10,
            "remaining": 0,
            "quota_used": 5,
            "quota_limit": 5,
        }


def test_per_key_quota_still_enforced_after_auth(monkeypatch):
    fake = _FakeUserLimiter()
    monkeypatch.setattr(facade, "ratelimiter", _FakeLimiter())
    monkeypatch.setattr(facade, "user_ratelimiter", fake)
    monkeypatch.setattr(rl.settings, "api_key", "master")
    record = {"key_id": "k1", "tier": "FREE", "rate_limit_rpm": 10, "quota_monthly": 5}
    scope = _scope(headers=[(b"authorization", b"Bearer pry_abc123")], key=record)
    allowed, _stats, headers, api_key = asyncio.run(rl.resolve_rate_limit(scope, "1.2.3.4"))
    assert allowed is False
    assert api_key == "pry_abc123"
    assert fake.refreshed == ["k1"]
    assert fake.checked == ["k1"]
    assert headers["x-ratelimit-quota-used"] == "5"
    assert headers["x-ratelimit-quota-limit"] == "5"
