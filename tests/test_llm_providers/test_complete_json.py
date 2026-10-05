# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""complete_json coverage on a provider and through the registry."""

from __future__ import annotations

from dataclasses import replace

from pry.intelligence.llm.base import LLMResponse
from pry.intelligence.llm.registry import LLMRegistry
from tests.test_llm_providers.conftest import FakeProvider, _http_error


async def test_provider_complete_json_parses_fenced_json() -> None:
    provider = FakeProvider(
        outcomes=[
            LLMResponse(
                text='```json\n{"risk_level": "red", "score": "5"}\n```',
                model="m",
                provider="fake",
                input_tokens=10,
                output_tokens=4,
            )
        ]
    )
    result = await provider.complete_json(
        "prompt", schema={"risk_level": "str", "score": "int"}, system="be strict"
    )
    assert result["risk_level"] == "red"
    assert result["score"] == 5
    assert result["llm_provider"] == "fake"
    assert result["llm_input_tokens"] == 10


async def test_provider_complete_json_returns_fallback_on_bad_json() -> None:
    provider = FakeProvider(outcomes=[LLMResponse(text="not json", model="m", provider="fake")])
    result = await provider.complete_json("prompt", fallback={"risk_level": "unknown"})
    assert result["risk_level"] == "unknown"
    assert result["llm_provider"] == "fake"
    assert result["llm_cost_usd"] == 0.0


async def test_registry_complete_json_happy_path() -> None:
    reg = LLMRegistry()
    provider = FakeProvider(
        name="b",
        outcomes=[
            LLMResponse(
                text='```json\n{"risk_level": "yellow", "score": "77"}\n```',
                model="m",
                provider="b",
                input_tokens=12,
                output_tokens=6,
            )
        ],
    )
    reg.register(provider)
    result = await reg.complete_json("prompt", schema={"risk_level": "str", "score": "int"})
    assert result["risk_level"] == "yellow"
    assert result["score"] == 77
    assert result["llm_provider"] == "b"
    assert reg.usage["b"]["calls"] == 1


async def test_registry_complete_json_falls_through_to_next_provider() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=0, base_delay=0.001)
    bad = FakeProvider(name="a", outcomes=[_http_error(429)])
    good = FakeProvider(
        name="b", outcomes=[LLMResponse(text='{"ok": true}', model="m", provider="b")]
    )
    reg.register(bad)
    reg.register(good)
    result = await reg.complete_json("prompt")
    assert result["ok"] is True
    assert result["llm_provider"] == "b"


async def test_registry_complete_json_all_fail_returns_fallback() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=0, base_delay=0.001)
    reg.register(FakeProvider(name="a", outcomes=[_http_error(503)]))
    result = await reg.complete_json("prompt", fallback={"risk_level": "unknown"})
    assert result["risk_level"] == "unknown"
    assert "error" in result


async def test_registry_complete_json_parse_failure_returns_fallback() -> None:
    reg = LLMRegistry()
    reg.register(
        FakeProvider(name="a", outcomes=[LLMResponse(text="nope", model="m", provider="a")])
    )
    result = await reg.complete_json("prompt", fallback={"risk_level": "unknown"})
    assert result["risk_level"] == "unknown"
    assert result["llm_provider"] == "a"  # provider responded; parse failed
