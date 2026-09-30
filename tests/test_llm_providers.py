# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for LLM provider system.

Covers the AI-forward LLM layer: schema-validated JSON completions, provider
fallback + retry with backoff, cost tracking, SSE streaming, and provider
ordering. The HTTP layer is fully mocked — no live keys, no network.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pry.intelligence.llm.base import (
    LLMCostTracker,
    LLMError,
    LLMProvider,
    LLMResponse,
    ReferralConfig,
    _stream_openai_compatible,
    coerce_to_schema,
    cost_tracker,
    parse_json_response,
    strip_fences,
)
from pry.intelligence.llm.registry import LLMRegistry, _provider_order_from_env
from tests.env_isolation import LLM_PROVIDER_KEY_FIELDS, clear_llm_keys

# ── Test doubles ──────────────────────────────────────────────────


class FakeProvider(LLMProvider):
    """Configurable fake provider: scripted outcomes or default success."""

    name = "fake"

    def __init__(
        self,
        name: str = "fake",
        outcomes: list[LLMResponse | Exception] | None = None,
        cost_in: float = 0.0,
        cost_out: float = 0.0,
    ) -> None:
        self.name = name
        self.outcomes = list(outcomes or [])
        self.calls = 0
        self.cost_per_1k_input = cost_in
        self.cost_per_1k_output = cost_out

    async def complete(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return LLMResponse(text="ok", model="fake", provider=self.name)

    async def embed(self, *args, **kwargs) -> list[float]:
        return []

    async def stream_chat(self, *args, **kwargs):
        response = await self.complete(*args, **kwargs)
        yield response.text


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"status {status}", request=request, response=response)


@pytest.fixture(autouse=True)
def _llm_hermetic(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate usage persistence + referral writes; reset the cost tracker."""
    monkeypatch.setattr("pry.intelligence.llm.registry.USAGE_DIR", tmp_path)
    monkeypatch.setattr("pry.commerce.referrals.ReferralTracker", MagicMock)
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── Existing coverage ─────────────────────────────────────────────


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


# ── JSON parsing / schema coercion ────────────────────────────────


def test_strip_fences() -> None:
    assert strip_fences('{"a": 1}') == '{"a": 1}'
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('\n\n  {"a": 1}  \n\n') == '{"a": 1}'


def test_parse_json_response_fenced_with_schema() -> None:
    schema = {"score": "int", "ok": "bool"}
    data = parse_json_response('```json\n{"score": "42", "ok": "true"}\n```', schema)
    assert data["score"] == 42
    assert data["ok"] is True


def test_parse_json_response_fallback_on_garbage() -> None:
    fallback = {"score": 0}
    data = parse_json_response("sorry, no json here", fallback=fallback)
    assert data == {"score": 0}
    # The caller's fallback dict must not be mutated by later calls.
    fallback["extra"] = True
    assert "extra" not in parse_json_response("nope", fallback={"score": 0})


def test_parse_json_response_fallback_on_non_object() -> None:
    assert parse_json_response("[1,2,3]", fallback={"x": 1}) == {"x": 1}


def test_coerce_to_schema_types_and_enums() -> None:
    schema = {
        "score": "int",
        "ratio": "float",
        "ok": "bool",
        "risk": "green|yellow|red",
        "nested": {"sub": "float"},
        "tags": {"type": "list"},
        "missing": "str",
    }
    data = coerce_to_schema(
        {
            "score": "87",
            "ratio": "0.5",
            "ok": "yes",
            "risk": "GREEN",
            "nested": {"sub": "2.5"},
            "tags": ["a", "b"],
            "unknown_key": "kept",
        },
        schema,
    )
    assert data["score"] == 87
    assert data["ratio"] == 0.5
    assert data["ok"] is True
    assert data["risk"] == "GREEN"
    assert data["nested"] == {"sub": 2.5}
    assert data["tags"] == ["a", "b"]
    assert data["missing"] is None
    assert data["unknown_key"] == "kept"


def test_coerce_to_schema_never_crashes_on_uncoercible() -> None:
    data = coerce_to_schema({"score": {"oops": 1}}, {"score": "int"})
    assert data["score"] == {"oops": 1}


# ── complete_json on a provider ───────────────────────────────────


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


# ── Cost tracking ─────────────────────────────────────────────────


def test_cost_tracker_records_and_resets() -> None:
    tracker = LLMCostTracker()
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p1", input_tokens=10, output_tokens=5, cost_usd=0.001
        )
    )
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p1", input_tokens=2, output_tokens=1, cost_usd=0.0001
        )
    )
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p2", input_tokens=7, output_tokens=3, cost_usd=0.0005
        )
    )
    stats = tracker.stats()
    assert stats["calls"] == 3
    assert stats["input_tokens"] == 19
    assert stats["output_tokens"] == 9
    assert stats["per_provider"]["p1"]["calls"] == 2
    tracker.reset()
    assert tracker.stats()["calls"] == 0


async def test_registry_tracks_cost_via_cost_tracker() -> None:
    reg = LLMRegistry()
    provider = FakeProvider(
        name="costprov",
        outcomes=[
            LLMResponse(
                text="ok", model="m", provider="costprov", input_tokens=1000, output_tokens=500
            )
        ],
        cost_in=0.001,
        cost_out=0.002,
    )
    reg.register(provider)
    await reg.complete("hi", fallback=False)
    stats = cost_tracker.stats()
    assert stats["per_provider"]["costprov"]["calls"] == 1
    assert abs(stats["per_provider"]["costprov"]["cost_usd"] - 0.002) < 1e-9


# ── Fallback + retry ──────────────────────────────────────────────


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


# ── complete_json through the registry ────────────────────────────


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


# ── Provider ordering ─────────────────────────────────────────────


def test_provider_order_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_LLM_PROVIDER_ORDER", " openrouter, OpenAi ,ollama ")
    assert _provider_order_from_env() == ["openrouter", "openai", "ollama"]
    monkeypatch.delenv("PRY_LLM_PROVIDER_ORDER", raising=False)
    assert _provider_order_from_env() == []


async def test_get_registry_respects_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_keys(monkeypatch, LLM_PROVIDER_KEY_FIELDS)
    monkeypatch.setenv("PRY_LLM_PROVIDER_ORDER", "openai,ollama")
    with patch("pry.intelligence.llm.registry._registry", None):
        from pry.intelligence.llm.registry import get_registry

        reg = get_registry()
    assert reg.fallback_chain == ["ollama"]


# ── Streaming ─────────────────────────────────────────────────────


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
    assert chunks == ["Hello", " world"]


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
    assert chunks == ["Hello", " world"]


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
    assert chunks == ["chunked"]


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
    assert results == [{"risk_level": "red"}]
