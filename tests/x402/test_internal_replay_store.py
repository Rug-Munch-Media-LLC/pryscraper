"""Shared seen-signature store: the shared path and the fail-open fallback.

The per-process ``_SEEN_SIGNATURES`` OrderedDict is correct at ``--workers 1``
and wrong at N — a captured internal request replayed against a *different*
worker is invisible to it. These tests pin the two halves of the fix:

1. With a usable Redis the seen-set is shared, so a signature consumed by one
   "worker" is refused by another, and the TTL matches the skew window.
2. Without Redis, or with Redis down, the gate degrades to the per-process
   cache and NEVER rejects on infrastructure grounds.

No live Redis: the fake is injected through the store's ``client`` seam, so the
real ``_get_client`` / ``SET NX EX`` / cooldown code all run for real.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import time
from typing import Any

import pytest

from pry.payments.x402_middleware import internal_replay_selection
from pry.payments.x402_middleware.internal import (
    _SEEN_SIGNATURES,
    REPLAY_TTL_SECONDS,
    _already_seen,
    internal_max_skew,
)
from pry.payments.x402_middleware.internal_replay_store import (
    KEY_PREFIX,
    RedisSeenSignatures,
)

REDIS_URL = "redis://fake:6379/0"


class FakeRedis:
    """Minimal ``SET NX EX`` surface with a hard failure switch.

    ``set`` returns True when the key was created (first use) and None when it
    already existed — exactly what redis-py does, which is what makes
    ``stored is None`` a correct replay test.
    """

    def __init__(self) -> None:
        self.keys: dict[str, int] = {}
        self.expiry: dict[str, int] = {}
        self.calls = 0
        self.pings = 0
        self.broken = False

    def ping(self) -> bool:
        self.pings += 1
        if self.broken:
            raise ConnectionError("redis is down")
        return True

    def set(self, key: str, value: str, *, nx: bool = False, ex: int = 0) -> bool | None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.calls += 1
        if nx and key in self.keys:
            return None
        self.keys[key] = 1
        self.expiry[key] = ex
        return True


@pytest.fixture(autouse=True)
def _clean_replay_state() -> Any:
    """Keep the module globals from leaking between tests."""
    _SEEN_SIGNATURES.clear()
    internal_replay_selection._STORE = None
    internal_replay_selection._PROBED_AT = 0.0
    yield
    _SEEN_SIGNATURES.clear()
    internal_replay_selection._STORE = None
    internal_replay_selection._PROBED_AT = 0.0


def _use_fake(fake: FakeRedis) -> None:
    """Adopt a fake Redis as the gate's shared store (no env/monkeypatch)."""
    internal_replay_selection.install(
        RedisSeenSignatures(REDIS_URL, REPLAY_TTL_SECONDS, client=fake)
    )
    internal_replay_selection._PROBED_AT = time.time()


def _store(fake: FakeRedis) -> RedisSeenSignatures:
    return RedisSeenSignatures(REDIS_URL, REPLAY_TTL_SECONDS, client=fake)


# ── Shared path ──────────────────────────────────────────────────────────────


def test_replay_is_refused_across_workers_when_shared() -> None:
    """The bug: a replay that lands on another worker must still be refused.

    Worker A claims the signature, then the process cache is emptied to
    simulate a different worker with an empty in-process cache. Without the
    shared store the replay would be served.
    """
    fake = FakeRedis()
    _use_fake(fake)
    assert _already_seen("sig-abc", time.time()) is False

    _SEEN_SIGNATURES.clear()  # worker B: fresh process, empty local cache
    assert _already_seen("sig-abc", time.time()) is True
    assert fake.calls == 2
    # Nothing reached the local cache: the shared set is authoritative.
    assert len(_SEEN_SIGNATURES) == 0


def test_redis_ttl_matches_the_skew_window() -> None:
    """A signature is remembered exactly as long as it could be replayed."""
    fake = FakeRedis()
    _use_fake(fake)
    _already_seen("sig-ttl", time.time())
    assert fake.expiry[KEY_PREFIX + "sig-ttl"] == REPLAY_TTL_SECONDS
    # The TTL must outlast the window it protects, or entries expire early and
    # a still-valid captured signature becomes replayable.
    assert 2 * internal_max_skew() <= REPLAY_TTL_SECONDS


def test_shared_store_is_atomic_per_signature() -> None:
    """SET NX is what makes the claim atomic across workers."""
    fake = FakeRedis()
    store = _store(fake)
    assert store.already_seen("sig-atomic", time.time()) is False
    assert store.already_seen("sig-atomic", time.time()) is True
    assert fake.calls == 2


def test_probe_adopts_only_a_working_client() -> None:
    """A broken client is refused at probe time, so it is never adopted."""
    assert _store(FakeRedis()).probe() is True
    broken = FakeRedis()
    broken.broken = True
    assert _store(broken).probe() is False


# ── Fail-open fallback ───────────────────────────────────────────────────────


def test_falls_back_when_no_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Redis configured: the pre-existing per-process cache is used."""
    # The selection seam is `configured_redis_url`; the gate must fall back
    # to the per-process cache when it yields no store.
    monkeypatch.setattr(internal_replay_selection, "configured_redis_url", lambda: "")
    # Behaviour, not internals: with no Redis the per-process cache still
    # de-duplicates, which is what "fail open" has to mean.
    assert _already_seen("sig-none", time.time()) is False
    assert _already_seen("sig-none", time.time()) is True


def test_falls_back_when_redis_is_unreachable() -> None:
    """Redis down: the gate serves, it does not 402 our own first-party jobs."""
    fake = FakeRedis()
    fake.broken = True
    _use_fake(fake)
    assert _already_seen("sig-down", time.time()) is False
    assert _already_seen("sig-down", time.time()) is True
    assert "sig-down" in _SEEN_SIGNATURES


def test_falls_back_when_redis_fails_mid_flight() -> None:
    """A store that dies between requests degrades instead of raising."""
    fake = FakeRedis()
    _use_fake(fake)
    assert _already_seen("sig-first", time.time()) is False
    fake.broken = True
    assert _already_seen("sig-second", time.time()) is False
    assert "sig-second" in _SEEN_SIGNATURES


def test_unreachable_redis_is_not_redialed_every_request() -> None:
    """A dead Redis is dialled on a cooldown, not once per internal request."""
    fake = FakeRedis()
    fake.broken = True
    _use_fake(fake)
    store = internal_replay_selection._STORE
    assert store is not None
    for i in range(5):
        assert _already_seen(f"sig-{i}", time.time()) is False
    # The cooldown that matters lives inside the store: one failed ping trips
    # it, so the remaining four requests are served from the per-process cache
    # without dialling a known-dead Redis again.
    assert store._client is None
    assert fake.pings == 1
