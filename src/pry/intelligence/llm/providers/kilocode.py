# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""kilocode LLM provider."""

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
        from pry.api.client import get_client

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
