# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""cohere LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
)


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
        from pry.api.client import get_client

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
        from pry.api.client import get_client

        client = await get_client()
        resp = await client.post(
            "https://api.cohere.ai/v1/embed",
            json={"texts": [text], "model": model, "input_type": "search_document"},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
