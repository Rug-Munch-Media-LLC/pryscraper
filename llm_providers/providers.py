# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Concrete LLM provider implementations."""

from __future__ import annotations

import logging
import os

from llm_providers.base import LLMProvider, LLMResponse
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
            timeout=60,
        )
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

    async def embed(self, text, model="text-embedding-3-small"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            json={"input": text, "model": model},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
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
            timeout=60,
        )
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
        resp = await client.post(url, json=body, timeout=60)
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
        resp = await client.post(url, json={"content": {"parts": [{"text": text}]}}, timeout=30)
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
            timeout=60,
        )
        data = resp.json()
        return LLMResponse(text=data["text"], model=model, provider=self.name, raw=data)

    async def embed(self, text, model="embed-english-v3.0"):
        from client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.cohere.ai/v1/embed",
            json={"texts": [text], "model": model, "input_type": "search_document"},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        return resp.json()["embeddings"][0]


class MistralProvider(LLMProvider):
    name = "mistral"
    cost_per_1k_input = 0.0002
    cost_per_1k_output = 0.0006
    referral_url = "https://console.mistral.ai/?ref=pry"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="mistral-small-latest"
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
            timeout=60,
        )
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
            timeout=30,
        )
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
        resp = await client.post(f"{self.base_url}/api/generate", json=body, timeout=300)
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
            f"{self.base_url}/api/embeddings", json={"model": model, "prompt": text}, timeout=60
        )
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
            timeout=60,
        )
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
        raise NotImplementedError("OpenRouter focuses on chat; use dedicated embedding providers")


def register_default_providers(registry: LLMRegistry) -> None:
    """Register all providers whose API keys are set in environment."""
    api_key_map = {
        "openai": os.getenv("OPENAI_API_KEY"),
        "anthropic": os.getenv("ANTHROPIC_API_KEY"),
        "google": os.getenv("GOOGLE_API_KEY"),
        "cohere": os.getenv("COHERE_API_KEY"),
        "mistral": os.getenv("MISTRAL_API_KEY"),
        "openrouter": os.getenv("OPENROUTER_API_KEY"),
    }
    provider_classes = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "cohere": CohereProvider,
        "mistral": MistralProvider,
        "openrouter": OpenRouterProvider,
    }
    for name, cls in provider_classes.items():
        key = api_key_map.get(name)
        if key:
            registry.register(cls(api_key=key))
    # Ollama is always available if running locally
    registry.register(OllamaProvider())
