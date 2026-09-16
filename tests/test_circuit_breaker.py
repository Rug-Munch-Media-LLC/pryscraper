# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.engine.circuit_breaker — per-domain semaphore registry and
tier→breaker mapping. No live infra.
"""

from __future__ import annotations

import asyncio

import pytest

from pry.engine import circuit_breaker as cb


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Isolate the module-global semaphore registry between tests."""
    cb._domain_semaphores.clear()
    yield
    cb._domain_semaphores.clear()


class TestBreakerForTier:
    def test_mapping_exact(self) -> None:
        assert cb.BREAKER_FOR_TIER == {
            "flaresolverr": "flaresolverr",
            "playwright": "playwright",
            "camoufox": "camoufox",
            "tls_fingerprint": "tls_fingerprint",
        }

    def test_domain_max_concurrency(self) -> None:
        assert cb.DOMAIN_MAX_CONCURRENCY == 10


class TestDomainSemaphore:
    def test_returns_semaphore_with_configured_limit(self) -> None:
        sem = cb.domain_semaphore("example.com")
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == cb.DOMAIN_MAX_CONCURRENCY

    def test_same_domain_returns_identical_object(self) -> None:
        first = cb.domain_semaphore("example.com")
        second = cb.domain_semaphore("example.com")
        assert first is second

    def test_different_domains_get_distinct_semaphores(self) -> None:
        a = cb.domain_semaphore("a.com")
        b = cb.domain_semaphore("b.com")
        assert a is not b

    def test_registry_tracks_each_domain(self) -> None:
        cb.domain_semaphore("a.com")
        cb.domain_semaphore("b.com")
        assert set(cb._domain_semaphores) == {"a.com", "b.com"}

    def test_lru_eviction_at_cap(self) -> None:
        for i in range(cb._DOMAIN_SEMAPHORE_MAX):
            cb.domain_semaphore(f"d{i}.com")
        assert len(cb._domain_semaphores) == cb._DOMAIN_SEMAPHORE_MAX
        # Adding one more evicts the oldest (d0.com).
        cb.domain_semaphore("overflow.com")
        assert len(cb._domain_semaphores) == cb._DOMAIN_SEMAPHORE_MAX
        assert "d0.com" not in cb._domain_semaphores
        assert "overflow.com" in cb._domain_semaphores

    def test_evicted_domain_recreated_fresh(self) -> None:
        for i in range(cb._DOMAIN_SEMAPHORE_MAX):
            cb.domain_semaphore(f"d{i}.com")
        cb.domain_semaphore("overflow.com")  # evicts d0.com
        recreated = cb.domain_semaphore("d0.com")
        assert recreated._value == cb.DOMAIN_MAX_CONCURRENCY
        assert "d0.com" in cb._domain_semaphores

    def test_semaphore_actually_limits_concurrency(self) -> None:
        sem = cb.domain_semaphore("limited.com")
        assert sem.locked() is False
        for _ in range(cb.DOMAIN_MAX_CONCURRENCY):
            sem._value -= 1
        assert sem.locked() is True
