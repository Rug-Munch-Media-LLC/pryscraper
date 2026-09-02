# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""anthropic LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
)


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
        from pry.api.client import get_client

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
