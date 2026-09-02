# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""openai LLM provider."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
    _stream_openai_compatible,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
        from pry.api.client import get_client

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
        from pry.api.client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            json={"input": text, "model": model},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
