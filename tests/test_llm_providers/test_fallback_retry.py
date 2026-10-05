# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fallback + retry behaviour of the registry."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pry.intelligence.llm.base import LLMError, LLMResponse
from pry.intelligence.llm.registry import LLMRegistry
from tests.test_llm_providers.conftest import FakeProvider, _http_error


async def test_registry_retries_transient_then_success() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=2, base_delay=0.001)
    provider = FakeProvider(
        outcomes=[
            _http_error(429),
            _http_error(429),
            LLMResponse(text="ok", model="m", provider="fake"),
        ]
    )
    reg.register(provider)
    result = await reg.complete("hi", fallback=False)
    assert result.text == "ok"
    assert provider.calls == 3


async def test_registry_falls_through_on_transient_exhausted() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=1, base_delay=0.001)
    always_429 = FakeProvider(name="a", outcomes=[_http_error(429), _http_error(429)])
    backup = FakeProvider(name="b", outcomes=[LLMResponse(text="backup", model="m", provider="b")])
    reg.register(always_429)
    reg.register(backup)
    result = await reg.complete("hi")
    assert result.provider == "b"
    assert result.text == "backup"
    assert always_429.calls == 2  # 1 initial + 1 retry, then fall through


async def test_registry_non_transient_skips_retry_and_falls_through() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=3, base_delay=0.001)
    bad_key = FakeProvider(name="a", outcomes=[_http_error(401)])
    backup = FakeProvider(name="b", outcomes=[LLMResponse(text="backup", model="m", provider="b")])
    reg.register(bad_key)
    reg.register(backup)
    result = await reg.complete("hi")
    assert result.provider == "b"
    assert bad_key.calls == 1  # 401 is not transient — no retry


async def test_registry_raises_when_all_providers_fail() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=0, base_delay=0.001)
    reg.register(FakeProvider(name="a", outcomes=[_http_error(500)]))
    with pytest.raises(LLMError):
        await reg.complete("hi", fallback=False)


async def test_complete_or_empty_on_total_failure() -> None:
    reg = LLMRegistry()
    reg.retry_config = replace(reg.retry_config, max_retries=0, base_delay=0.001)
    reg.register(FakeProvider(name="a", outcomes=[_http_error(500)]))
    result = await reg.complete_or_empty("hi")
    assert result.text == ""
    assert result.provider == "none"
