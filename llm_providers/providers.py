# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Concrete LLM provider implementations."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from llm_providers.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
    _stream_openai_compatible,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from llm_providers.registry import LLMRegistry

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    name = "openai"
    cost_per_1k_input = 0.00015  # gpt-4o-mini
    cost_per_1k_output = 0.0006
    referral_url = "https://platform.openai.com/signup?via=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="gpt-4o-mini"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return LLMResponse(
            text=choice["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            raw=data,
        )

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "gpt-4o-mini",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas via the OpenAI chat completions SSE endpoint."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://api.openai.com/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=LLM_TIMEOUT_SECONDS,
        ):
            yield chunk

    async def embed(self, text, model="text-embedding-3-small"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            json={"input": text, "model": model},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    cost_per_1k_input = 0.00025  # claude-3-haiku
    cost_per_1k_output = 0.00125
    referral_url = "https://console.anthropic.com/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="claude-3-haiku-20240307"
    ):
        from client import get_client

        client = await get_client()
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=body,
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            text=data["content"][0]["text"],
            model=model,
            provider=self.name,
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
            raw=data,
        )

    async def embed(self, text, model=""):
        raise NotImplementedError("Anthropic doesn't have a public embedding API yet")


class GoogleProvider(LLMProvider):
    name = "google"
    cost_per_1k_input = 0.000125  # gemini-flash
    cost_per_1k_output = 0.000375
    referral_url = "https://aistudio.google.com/?utm_source=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="gemini-1.5-flash"
    ):
        from client import get_client

        client = await get_client()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        body = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        resp = await client.post(url, json=body, timeout=LLM_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            raw=data,
        )

    async def embed(self, text, model="text-embedding-004"):
        from client import get_client

        client = await get_client()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={self.api_key}"
        resp = await client.post(
            url, json={"content": {"parts": [{"text": text}]}}, timeout=LLM_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return resp.json()["embedding"]["values"]


class CohereProvider(LLMProvider):
    name = "cohere"
    cost_per_1k_input = 0.0001
    cost_per_1k_output = 0.0004
    referral_url = "https://dashboard.cohere.com/welcome?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("COHERE_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="command-r"
    ):
        from client import get_client

        client = await get_client()
        body = {
            "model": model,
            "message": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["preamble"] = system
        resp = await client.post(
            "https://api.cohere.ai/v1/chat",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(text=data["text"], model=model, provider=self.name, raw=data)

    async def embed(self, text, model="embed-english-v3.0"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.cohere.ai/v1/embed",
            json={"texts": [text], "model": model, "input_type": "search_document"},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]


class MistralProvider(LLMProvider):
    name = "mistral"
    cost_per_1k_input = 0.0  # Free tier: open-mistral-nemo
    cost_per_1k_output = 0.0
    referral_url = "https://console.mistral.ai/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="open-mistral-nemo"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            raw=data,
        )

    async def embed(self, text, model="mistral-embed"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.mistral.ai/v1/embeddings",
            json={"model": model, "input": [text]},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


class OllamaProvider(LLMProvider):
    name = "ollama"
    cost_per_1k_input = 0.0  # Self-hosted, free
    cost_per_1k_output = 0.0
    referral_url = "https://ollama.com"  # No referral program, just self-hosted

    def __init__(self, base_url: str = "", model: str = "llama3.2"):
        self.base_url = base_url or os.getenv("PRY_OLLAMA_URL", "http://localhost:11434")
        self.default_model = model

    async def complete(self, prompt, system="", max_tokens=1024, temperature=0.7, model=""):
        from client import get_client

        client = await get_client()
        model = model or self.default_model
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            body["system"] = system
        resp = await client.post(
            f"{self.base_url}/api/generate", json=body, timeout=LLM_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            text=data["response"],
            model=model,
            provider=self.name,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            raw=data,
        )

    async def embed(self, text, model=""):
        from client import get_client

        client = await get_client()
        model = model or "nomic-embed-text"
        resp = await client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


class OpenRouterProvider(LLMProvider):
    name = "openrouter"
    cost_per_1k_input = 0.0  # Free models available
    cost_per_1k_output = 0.0
    referral_url = "https://openrouter.ai/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    async def complete(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="meta-llama/llama-3.2-3b-instruct:free",
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "meta-llama/llama-3.2-3b-instruct:free",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas via the OpenRouter chat completions SSE endpoint."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=LLM_TIMEOUT_SECONDS,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("OpenRouter focuses on chat; use dedicated embedding providers")


class KiloCodeProvider(LLMProvider):
    """KiloCode provider - free models via KiloCode gateway.

    Models available (free tier):
    - kilo-auto/free (auto-routing to best free model)
    - stepfun/step-3.7-flash:free (262K ctx)
    - nvidia/nemotron-3-ultra-550b-a55b:free (1M ctx)
    - nvidia/nemotron-3-super-120b-a12b:free (128K ctx)
    - nvidia/nemotron-3.5-lightning:free (128K ctx)
    - poolside/laguna-s-2.1:free (262K ctx)
    - poolside/laguna-xs-2.1:free (262K ctx)
    - tencent/hy3:free (128K ctx)
    - cohere/north-mini-code:free (128K ctx)
    - dots-studio/dots-3-note-preview:free (128K ctx)
    - nvidia/nemotron-3.5-content-safety:free (128K ctx)
    - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free (128K ctx)
    - openrouter/free (meta-router)
    """

    name = "kilocode"
    cost_per_1k_input = 0.0  # Free tier
    cost_per_1k_output = 0.0
    referral_url = "https://kilocode.ai"

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or os.getenv("KILOCODE_API_KEY", "")
        # BYOK: consumers point this at their own KiloCode-compatible gateway
        # via KILOCODE_BASE_URL — there is no universal public endpoint.
        self.base_url = base_url or os.getenv("KILOCODE_BASE_URL", "")

    async def complete(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="kilo-auto/free",
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        choice = data["choices"][0]
        message = choice.get("message", {})
        # Some models (e.g., StepFun) return response in reasoning field instead of content
        text = message.get("content", "") or message.get("reasoning", "")
        return LLMResponse(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "kilo-auto/free",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas via the KiloCode gateway SSE endpoint."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url=self.base_url,
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=LLM_TIMEOUT_SECONDS,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("KiloCode focuses on chat; use dedicated embedding providers")


class DeepSeekProvider(LLMProvider):
    """DeepSeek V4 API - paid but fast and high quality."""

    name = "deepseek"
    cost_per_1k_input = 0.0  # Paid but low cost
    cost_per_1k_output = 0.0
    referral_url = "https://platform.deepseek.com/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="deepseek-chat"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="deepseek-chat", **kwargs
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://api.deepseek.com/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("DeepSeek doesn't offer public embedding API")


class GroqProvider(LLMProvider):
    """Groq API - free tier with Llama/Mixtral models."""

    name = "groq"
    cost_per_1k_input = 0.0  # Free tier
    cost_per_1k_output = 0.0
    referral_url = "https://groq.com/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="llama-3.3-70b-versatile"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="llama-3.3-70b-versatile",
        **kwargs,
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://api.groq.com/openai/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("Groq focuses on chat inference")


class KimiProvider(LLMProvider):
    """Kimi API - Moonshot AI (Chinese LLM provider)."""

    name = "kimi"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://kimi.moonshot.cn/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("KIMI_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="kimi-latest"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.moonshot.cn/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, text, model=""):
        raise NotImplementedError("Kimi doesn't offer public embedding API")


class NvidiaProvider(LLMProvider):
    """NVIDIA NIM API - free tier with Nemotron models."""

    name = "nvidia"
    cost_per_1k_input = 0.0  # Free tier
    cost_per_1k_output = 0.0
    referral_url = "https://build.nvidia.com/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY", "")

    async def complete(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="meta/llama-3.1-8b-instruct",
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="meta/llama-3.1-8b-instruct",
        **kwargs,
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("NVIDIA NIM focuses on chat inference")


class NousProvider(LLMProvider):
    """Nous Research API."""

    name = "nous"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://nousresearch.com/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("NOUS_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="nous-hermes-3"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.nousresearch.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, text, model=""):
        raise NotImplementedError("Nous doesn't offer public embedding API")


class ZaiProvider(LLMProvider):
    """Z.ai API."""

    name = "zai"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://z.ai/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("ZAI_API_KEY", "")

    async def complete(self, prompt, system="", max_tokens=1024, temperature=0.7, model="zai-chat"):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.z.ai/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, text, model=""):
        raise NotImplementedError("Z.ai doesn't offer public embedding API")


class CerebrasProvider(LLMProvider):
    """Cerebras API - wafer-scale AI inference."""

    name = "cerebras"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://cerebras.ai/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("CEREBRAS_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="llama3.1-8b"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.cerebras.ai/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="llama3.1-8b", **kwargs
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url="https://api.cerebras.ai/v1",
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("Cerebras focuses on fast inference")


class MinimaxProvider(LLMProvider):
    """MiniMax API (Hailuo AI)."""

    name = "minimax"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://minimax.io/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="minimax-chat"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            "https://api.minimax.io/v1/text/chatcompletion_v2",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def embed(self, text, model=""):
        raise NotImplementedError("MiniMax focuses on chat")


class SiliconFlowProvider(LLMProvider):
    """SiliconFlow API - Chinese cloud LLM provider (OpenAI-compatible)."""

    name = "siliconflow"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://siliconflow.cn/?ref=pry"

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        )

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="Qwen/Qwen2.5-7B-Instruct"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="Qwen/Qwen2.5-7B-Instruct",
        **kwargs,
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url=self.base_url,
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model="BAAI/bge-large-en-v1.5"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            f"{self.base_url}/embeddings",
            json={"model": model, "input": [text]},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


class OpenCodeZenProvider(LLMProvider):
    """OpenCode Zen API - free deepseek-v4-flash."""

    name = "opencode_zen"
    cost_per_1k_input = 0.0  # Always free
    cost_per_1k_output = 0.0
    referral_url = "https://opencode.ai/?ref=pry"

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or os.getenv("OPENCODE_ZEN_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "OPENCODE_ZEN_BASE_URL", "https://opencode.ai/api/zen/v1"
        )

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="deepseek-v4-flash-free"
    ):
        from client import get_client

        client = await get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def stream_chat(
        self,
        prompt,
        system="",
        max_tokens=1024,
        temperature=0.7,
        model="deepseek-v4-flash-free",
        **kwargs,
    ):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async for chunk in _stream_openai_compatible(
            base_url=self.base_url,
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def embed(self, text, model=""):
        raise NotImplementedError("OpenCode Zen doesn't offer embedding API")


def register_default_providers(registry: LLMRegistry) -> None:
    """Register all providers whose API keys are set in environment."""
    from settings import settings

    # BYOK (bring your own key): one account per provider. Consumers set
    # PRY_<PROVIDER>_API_KEY (or the provider's standard env var, which each
    # provider class falls back to). Multi-account fan-out is a deployment
    # concern, not a product concern — run multiple instances or a router.
    api_key_map = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.gemini_api_key,
        "cohere": settings.cohere_api_key,
        "mistral": settings.mistral_api_key,
        "openrouter": settings.openrouter_api_key,
        "kilocode": settings.kilocode_api_key,
        "deepseek": settings.deepseek_api_key,
        "groq": settings.groq_api_key,
        "kimi": settings.kimi_api_key,
        "nvidia": settings.nvidia_api_key,
        "nous": settings.nous_api_key,
        "zai": settings.zai_api_key,
        "cerebras": settings.cerebras_api_key,
        "minimax": settings.minimax_api_key,
        "siliconflow": settings.siliconflow_api_key,
        "opencode_zen": settings.opencode_zen_api_key,
    }
    provider_classes = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "cohere": CohereProvider,
        "mistral": MistralProvider,
        "openrouter": OpenRouterProvider,
        "kilocode": KiloCodeProvider,
        "deepseek": DeepSeekProvider,
        "groq": GroqProvider,
        "kimi": KimiProvider,
        "nvidia": NvidiaProvider,
        "nous": NousProvider,
        "zai": ZaiProvider,
        "cerebras": CerebrasProvider,
        "minimax": MinimaxProvider,
        "siliconflow": SiliconFlowProvider,
        "opencode_zen": OpenCodeZenProvider,
    }
    for name, cls in provider_classes.items():
        key = api_key_map.get(name)
        if key:
            registry.register(cls(api_key=key))
    # Ollama is always available if running locally (free, private)
    registry.register(OllamaProvider())
