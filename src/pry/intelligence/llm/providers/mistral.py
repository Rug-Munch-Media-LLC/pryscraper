# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""mistral LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
)


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
        from pry.api.client import get_client

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
        from pry.api.client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.mistral.ai/v1/embeddings",
            json={"model": model, "input": [text]},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
