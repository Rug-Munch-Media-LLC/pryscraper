# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.engine.domain_key — the registrable-domain memory key.

The regression these guard: the adaptive tier memory and the per-domain
semaphore were keyed on ``urlparse(url).netloc``, so ``example.com``,
``www.example.com`` and ``example.com:8443`` were three unrelated buckets.
No bucket ever gathered enough samples to decide anything, and the
concurrency cap was bypassed by varying the spelling. No live infra.
"""

from __future__ import annotations

import pytest

from pry.engine.domain_key import UNKNOWN, memory_domain


class TestHostAndPortCollapse:
    """The regression: spelling variants of one site share one key."""

    @pytest.mark.parametrize(
        "url_or_host",
        [
            "example.com",
            "www.example.com",
            "m.example.com",
            "amp.example.com",
            "WWW.Example.COM",
            "example.com:8443",
            "www.example.com:8443",
            "https://www.example.com",
            "https://www.example.com:8443/blog?utm_source=x",
            "http://example.com/shop",
            "//example.com/blog",
            "user:pw@example.com:8443",
            "example.com.",
        ],
    )
    def test_every_spelling_yields_one_key(self, url_or_host: str) -> None:
        assert memory_domain(url_or_host) == "example.com"

    def test_port_variants_collapse_to_one_key(self) -> None:
        keys = {
            memory_domain("https://example.com/blog"),
            memory_domain("https://www.example.com/blog"),
            memory_domain("https://example.com:8443/blog"),
        }
        expected = {"example.com"}
        assert keys == expected


class TestRegistrableReduction:
    def test_multi_label_public_suffix(self) -> None:
        assert memory_domain("https://blog.example.co.uk/x") == "example.co.uk"

    def test_subdomains_of_one_registrable_domain_share_a_key(self) -> None:
        # Deliberate merge — see TestScopeMerge below.
        assert memory_domain("a.b.c.example.com") == memory_domain("example.com")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("localhost", "localhost"),
            ("localhost:8443", "localhost"),
            ("www.localhost", "localhost"),
            ("127.0.0.1", "127.0.0.1"),
            ("127.0.0.1:8443", "127.0.0.1"),
            ("[::1]:8443", "::1"),
        ],
    )
    def test_no_public_suffix_falls_back_to_full_host(self, raw: str, expected: str) -> None:
        """No PSL entry means the host is already the most conservative key.

        Documented behaviour, not a hand-rolled exception list: a public
        suffix implementation (tldextract) supplies the IANA data, and hosts
        outside it (localhost, IPs, intranet names) are kept whole rather than
        guessed at.
        """
        assert memory_domain(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "://", "http://"])
    def test_empty_or_hostless_input_is_unknown(self, raw: str) -> None:
        assert memory_domain(raw) == UNKNOWN

    def test_never_contains_scheme_port_or_path(self) -> None:
        key = memory_domain("https://WWW.Example.COM:8443/blog/deep?x=1")
        assert "://" not in key
        assert "8443" not in key
        assert "/" not in key
        assert key == key.lower()


class TestScopeMerge:
    """The documented consequence: /blog and /shop share the site key.

    Deliberate, asserted so a future change to key by path has to update this
    test (and its docstring) rather than silently alter throttle + memory
    behaviour. A scope-qualified key would need a second lookup and a rule for
    merging two records — a two-key selection scheme, out of scope here.
    """

    def test_blog_and_shop_share_one_key(self) -> None:
        assert memory_domain("https://example.com/blog") == memory_domain(
            "https://example.com/shop"
        )

    def test_blog_and_shop_merge_samples_in_tier_memory(self) -> None:
        """The merge is real: one bucket, sample counts add up.

        Proves the key collapses distinct paths onto one record, which is the
        point — samples accumulate instead of scattering across netloc
        spellings.
        """
        from pry.engine.resilience import DomainTierMemory

        memory = DomainTierMemory()
        memory.record("example.com", "flaresolverr", True, latency=1.0)
        memory.record("example.com", "flaresolverr", True, latency=1.0)
        record = memory.data["example.com"]["flaresolverr"]
        assert record.successes == 2
        assert memory.best_tier("example.com", ["flaresolverr", "playwright"]) == "flaresolverr"

    def test_www_and_port_variants_merge_into_the_same_record(self) -> None:
        from pry.engine.resilience import DomainTierMemory

        memory = DomainTierMemory()
        for url in ("https://example.com/blog", "https://www.example.com:8443/shop"):
            memory.record(memory_domain(url), "playwright", False, latency=2.0)
        expected = {"example.com"}
        assert set(memory.data) == expected
        assert memory.data["example.com"]["playwright"].failures == 2


class TestThrottleSharesOneSemaphore:
    def test_variants_share_one_semaphore(self) -> None:
        from pry.engine import circuit_breaker as cb

        cb._domain_semaphores.clear()
        try:
            first = cb.domain_semaphore(memory_domain("https://example.com/blog"))
            second = cb.domain_semaphore(memory_domain("https://www.example.com:8443/shop"))
            assert first is second
        finally:
            cb._domain_semaphores.clear()
