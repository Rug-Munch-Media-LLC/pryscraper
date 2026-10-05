# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Registry, referral config, and provider cost-estimation coverage."""

from __future__ import annotations

from pry.intelligence.llm.base import LLMProvider, LLMResponse, ReferralConfig
from pry.intelligence.llm.registry import LLMRegistry


def test_referral_config() -> None:
    rc = ReferralConfig()
    assert rc.enabled is True
    assert "openai" in rc.referral_links
    assert "anthropic" in rc.referral_links
    assert "pry" in rc.referral_links["openai"]


def test_llm_registry_init() -> None:
    r = LLMRegistry()
    stats = r.get_stats()
    assert "providers" in stats
    assert "referral" in stats
    assert "fallback_chain" in stats


def test_llm_registry_register() -> None:
    r = LLMRegistry()

    class FakeProvider(LLMProvider):
        name = "fake"

        async def complete(self, *args, **kwargs):
            return LLMResponse(text="ok", model="fake", provider="fake")

        async def embed(self, *args, **kwargs):
            return [0.1, 0.2]

    r.register(FakeProvider())
    assert "fake" in r.providers


def test_llm_response_dataclass() -> None:
    r = LLMResponse(
        text="hello", model="m", provider="p", input_tokens=10, output_tokens=5, cost_usd=0.001
    )
    assert r.text == "hello"
    assert r.cost_usd == 0.001


def test_provider_cost_estimation() -> None:
    class TestProvider(LLMProvider):
        cost_per_1k_input = 0.001
        cost_per_1k_output = 0.002

        async def complete(self, *args, **kwargs):
            return LLMResponse(text="", model="t", provider="t")

        async def embed(self, *args, **kwargs):
            return []

    p = TestProvider()
    cost = p.estimate_cost(1000, 500)
    assert abs(cost - 0.002) < 0.0001  # 0.001 + 0.001


def test_referral_link_format() -> None:
    rc = ReferralConfig()
    for provider, link in rc.referral_links.items():
        # FlareSolverr is open-source, no affiliate
        if provider == "flaresolverr":
            continue
        assert "pry" in link, f"Link for {provider} missing referral: {link}"
