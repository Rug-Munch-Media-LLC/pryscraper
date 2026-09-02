# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""google LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
)


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
        from pry.api.client import get_client

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
        from pry.api.client import get_client

        client = await get_client()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={self.api_key}"
        resp = await client.post(
            url, json={"content": {"parts": [{"text": text}]}}, timeout=LLM_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return resp.json()["embedding"]["values"]
