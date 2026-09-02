# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""nvidia LLM provider."""

from __future__ import annotations

import os

from pry.intelligence.llm.base import (
    LLM_TIMEOUT_SECONDS,
    LLMProvider,
    LLMResponse,
    _stream_openai_compatible,
)


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
        from pry.api.client import get_client

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
