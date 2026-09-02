# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""local LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
)


class OllamaProvider(LLMProvider):
    name = "ollama"
    cost_per_1k_input = 0.0  # Self-hosted, free
    cost_per_1k_output = 0.0
    referral_url = "https://ollama.com"  # No referral program, just self-hosted

    def __init__(self, base_url: str = "", model: str = "llama3.2"):
        self.base_url = base_url or os.getenv("PRY_OLLAMA_URL", "http://localhost:11434")
        self.default_model = model

    async def complete(self, prompt, system="", max_tokens=1024, temperature=0.7, model=""):
        from pry.api.client import get_client

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
        from pry.api.client import get_client

        client = await get_client()
        model = model or "nomic-embed-text"
        resp = await client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
