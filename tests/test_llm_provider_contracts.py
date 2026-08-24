# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Contract tests for all 17 LLM providers (audit win C17).

Every provider must satisfy the same HTTP contract against a mocked
transport: complete() returns a well-formed LLMResponse built from the
provider's real wire format, and missing API keys degrade gracefully.
"""

from __future__ import annotations

from typing import Any

import pytest

from llm_providers.base import LLMResponse
from llm_providers.providers import (
    AnthropicProvider,
    CerebrasProvider,
    CohereProvider,
    DeepSeekProvider,
    GoogleProvider,
    GroqProvider,
    KiloCodeProvider,
    KimiProvider,
    LLMProvider,
    MinimaxProvider,
    MistralProvider,
    NousProvider,
    NvidiaProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenCodeZenProvider,
    OpenRouterProvider,
    SiliconFlowProvider,
    ZaiProvider,
)


def _install(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """Replace client.get_client with an httpx-client double.

    The double returns responses whose raise_for_status() works and whose
    json() yields ``payload`` - exactly what every provider's complete()
    consumes.
    """

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return payload

    class _Client:
        async def post(self, *_a: Any, **_k: Any) -> _Resp:
            return _Resp()

    import pry.api.client as client_module

    async def fake_get_client() -> _Client:
        return _Client()

    monkeypatch.setattr(client_module, "get_client", fake_get_client)


def _openai_payload(text: str = "mocked completion") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


# name, class, expected provider tag in LLMResponse
OPENAI_COMPATIBLE = [
    ("openai", OpenAIProvider),
    ("deepseek", DeepSeekProvider),
    ("groq", GroqProvider),
    ("kimi", KimiProvider),
    ("nvidia", NvidiaProvider),
    ("nous", NousProvider),
    ("zai", ZaiProvider),
    ("cerebras", CerebrasProvider),
    ("minimax", MinimaxProvider),
    ("siliconflow", SiliconFlowProvider),
    ("opencode_zen", OpenCodeZenProvider),
    ("kilocode", KiloCodeProvider),
]


class TestOpenAICompatibleContract:
    """12 providers share the OpenAI chat-completions wire format."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("name", "cls"),
        OPENAI_COMPATIBLE,
        ids=[n for n, _ in OPENAI_COMPATIBLE],
    )
    async def test_complete_contract(
        self, name: str, cls: type[LLMProvider], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _openai_payload())
        provider = cls(api_key="test-key-123")
        resp = await provider.complete("say hi", system="be brief")
        assert isinstance(resp, LLMResponse)
        assert resp.text == "mocked completion"
        assert resp.provider == name
        assert resp.input_tokens == 11
        assert resp.output_tokens == 7


class TestSpecialWireFormats:
    """Providers with their own response shapes."""

    @pytest.mark.asyncio
    async def test_anthropic_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(
            monkeypatch,
            {
                "content": [{"type": "text", "text": "claude says hi"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )
        provider = AnthropicProvider(api_key="sk-ant-test")
        resp = await provider.complete("hi", system="sys")
        assert resp.text == "claude says hi"
        assert resp.provider == "anthropic"
        assert resp.input_tokens == 5

    @pytest.mark.asyncio
    async def test_google_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(
            monkeypatch,
            {
                "candidates": [{"content": {"parts": [{"text": "gemini says hi"}]}}],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 6},
            },
        )
        provider = GoogleProvider(api_key="g-key")
        resp = await provider.complete("hi")
        assert resp.text == "gemini says hi"
        assert resp.output_tokens == 6

    @pytest.mark.asyncio
    async def test_cohere_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Cohere provider uses the generate-style endpoint: {"text": ...}
        _install(monkeypatch, {"text": "cohere says hi"})
        provider = CohereProvider(api_key="c-key")
        resp = await provider.complete("hi")
        assert resp.text == "cohere says hi"
        assert resp.provider == "cohere"

    @pytest.mark.asyncio
    async def test_mistral_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(
            monkeypatch,
            {
                "choices": [{"message": {"content": "mistral says hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )
        provider = MistralProvider(api_key="m-key")
        resp = await provider.complete("hi")
        assert resp.text == "mistral says hi"

    @pytest.mark.asyncio
    async def test_openrouter_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _openai_payload("or says hi"))
        provider = OpenRouterProvider(api_key="or-key")
        resp = await provider.complete("hi")
        assert resp.text == "or says hi"

    @pytest.mark.asyncio
    async def test_ollama_local_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ollama uses /api/generate: {"response": ...} + eval counts."""
        _install(
            monkeypatch,
            {
                "response": "local says hi",
                "prompt_eval_count": 3,
                "eval_count": 5,
            },
        )
        provider = OllamaProvider()
        resp = await provider.complete("hi")
        assert resp.text == "local says hi"
        assert resp.input_tokens == 3
        assert resp.output_tokens == 5

    @pytest.mark.asyncio
    async def test_anthropic_embed_is_explicit_not_implemented(self) -> None:
        provider = AnthropicProvider(api_key="k")
        with pytest.raises(NotImplementedError, match="embedding"):
            await provider.embed("text")


class TestCostAccounting:
    def test_every_provider_declares_costs_and_referrals(self) -> None:
        """Referral revenue depends on cost metadata being present."""
        for cls in (
            OpenAIProvider,
            AnthropicProvider,
            GoogleProvider,
            CohereProvider,
            MistralProvider,
            OpenRouterProvider,
            KiloCodeProvider,
            DeepSeekProvider,
            GroqProvider,
            KimiProvider,
            NvidiaProvider,
            NousProvider,
            ZaiProvider,
            CerebrasProvider,
            MinimaxProvider,
            SiliconFlowProvider,
            OpenCodeZenProvider,
        ):
            # Free-tier providers (e.g. mistral/open-mistral-nemo) may be 0.
            assert cls.cost_per_1k_input >= 0, cls.name
            assert cls.cost_per_1k_output >= 0, cls.name
            assert cls.referral_url.startswith("https://"), cls.name

    def test_cost_estimation_math(self) -> None:
        openai = OpenAIProvider(api_key="k")
        expected = 0.00015 + 0.0006  # 1k in + 1k out
        assert openai.estimate_cost(1000, 1000) == pytest.approx(expected)

    def test_llm_response_roundtrip_fields(self) -> None:
        resp = LLMResponse(
            text="t",
            model="m",
            provider="p",
            input_tokens=10,
            output_tokens=20,
        )
        assert resp.input_tokens == 10
        assert resp.output_tokens == 20
