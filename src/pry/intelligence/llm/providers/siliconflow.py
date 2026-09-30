# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""siliconflow LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
    _stream_openai_compatible,
)


class SiliconFlowProvider(LLMProvider):
    """SiliconFlow API - Chinese cloud LLM provider (OpenAI-compatible)."""

    name = "siliconflow"
    cost_per_1k_input = 0.0
    cost_per_1k_output = 0.0
    referral_url = "https://siliconflow.cn/?ref=pry"

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        # Default is the international host. api.siliconflow.cn rejects this
        # account's key with 401 "Token is invalid" on /v1/chat/completions,
        # /v1/embeddings and /v1/rerank alike, so a .cn default meant every
        # call failed unless SILICONFLOW_BASE_URL was exported. Verified working
        # 2026-09-30 against api.siliconflow.com.
        self.base_url = base_url or os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.com/v1"
        )

    async def complete(
        self, prompt, system="", max_tokens=1024, temperature=0.7, model="Qwen/Qwen2.5-7B-Instruct"
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
        from pry.api.client import get_client

        client = await get_client()
        resp = await client.post(
            f"{self.base_url}/embeddings",
            json={"model": model, "input": [text]},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
