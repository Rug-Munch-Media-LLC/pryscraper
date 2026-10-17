# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Provider ordering and SSE streaming coverage."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from pry.intelligence.llm.base import LLMResponse, _stream_openai_compatible
from pry.intelligence.llm.registry import LLMRegistry, _provider_order_from_env
from tests.env_isolation import LLM_PROVIDER_KEY_FIELDS, clear_llm_keys
from tests.test_llm_providers.conftest import FakeProvider, _http_error


def test_provider_order_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_LLM_PROVIDER_ORDER", " openrouter, OpenAi ,ollama ")
    expected = ["openrouter", "openai", "ollama"]
    assert _provider_order_from_env() == expected
    monkeypatch.delenv("PRY_LLM_PROVIDER_ORDER", raising=False)
    assert _provider_order_from_env() == []


async def test_get_registry_respects_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_keys(monkeypatch, LLM_PROVIDER_KEY_FIELDS)
    monkeypatch.setenv("PRY_LLM_PROVIDER_ORDER", "openai,ollama")
    with patch("pry.intelligence.llm.registry._registry", None):
        from pry.intelligence.llm.registry import get_registry

        reg = get_registry()
    expected = ["ollama"]
    assert reg.fallback_chain == expected


class FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.com/v1/chat/completions")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeStreamCM:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self._resp = FakeStreamResponse(status_code, lines)

    async def __aenter__(self) -> FakeStreamResponse:
        return self._resp

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeStreamClient:
    """Mimics httpx.AsyncClient.stream() for SSE tests."""

    def __init__(self, responses: list[tuple[int, list[str]]]) -> None:
        self._responses = list(responses)

    def stream(self, method: str, url: str, **kwargs):
        status, lines = self._responses.pop(0)
        return FakeStreamCM(status, lines)


SSE_LINES = [
    'data: {"choices":[{"delta":{"role":"assistant"}}]}',
    'data: {"choices":[{"delta":{"content":"Hello"}}]}',
    'data: {"choices":[{"delta":{"content":" world"}}]}',
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
    "data: [DONE]",
    "",
]


async def test_stream_openai_compatible_parses_sse() -> None:
    with patch("pry.api.client.get_client", return_value=FakeStreamClient([(200, SSE_LINES)])):
        chunks = [
            c
            async for c in _stream_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.0,
                retry_attempts=0,
            )
        ]
    expected = ["Hello", " world"]
    assert chunks == expected


async def test_stream_openai_compatible_retries_on_transient() -> None:
    responses = [(429, []), (200, SSE_LINES)]
    with patch("pry.api.client.get_client", return_value=FakeStreamClient(responses)):
        chunks = [
            c
            async for c in _stream_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="m",
                messages=[],
                max_tokens=100,
                temperature=0.0,
                retry_attempts=1,
                backoff_base=0.001,
            )
        ]
    expected = ["Hello", " world"]
    assert chunks == expected


async def test_stream_openai_compatible_raises_on_non_transient() -> None:
    with (
        patch("pry.api.client.get_client", return_value=FakeStreamClient([(401, [])])),
        pytest.raises(httpx.HTTPStatusError),
    ):
        _ = [
            c
            async for c in _stream_openai_compatible(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="m",
                messages=[],
                max_tokens=100,
                temperature=0.0,
                retry_attempts=2,
            )
        ]


async def test_registry_stream_chat_falls_through_providers() -> None:
    class FailingStreamProvider(FakeProvider):
        async def stream_chat(self, *args, **kwargs):
            raise _http_error(429)
            yield  # pragma: no cover

    reg = LLMRegistry()
    reg.register(FailingStreamProvider(name="a"))
    backup = FakeProvider(name="b", outcomes=[LLMResponse(text="chunked", model="m", provider="b")])
    reg.register(backup)
    chunks = [c async for c in reg.stream_chat("hi")]
    expected = ["chunked"]
    assert chunks == expected


async def test_provider_stream_json_buffers_and_parses() -> None:
    class StreamingJsonProvider(FakeProvider):
        async def stream_chat(self, *args, **kwargs):
            for part in ['{"risk_', 'level": "red"}']:
                yield part

    provider = StreamingJsonProvider()
    results = [
        r
        async for r in provider.stream_json(
            "prompt", schema={"risk_level": "green|yellow|red|unknown"}
        )
    ]
    expected = [{"risk_level": "red"}]
    assert results == expected
