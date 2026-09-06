"""Pry — OpenAI/OpenRouter-compatible SSE streaming helper.

Split out of ``base.py`` (2026-09-06) — see ``base.py`` for the re-export facade.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from pry.intelligence.llm.base_client import (
    LLM_STREAM_RETRY_ATTEMPTS,
    LLM_STREAM_RETRY_BACKOFF,
    LLM_TIMEOUT_SECONDS,
    TRANSIENT_HTTP_STATUSES,
)


async def _stream_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout_seconds: float = LLM_TIMEOUT_SECONDS,
    retry_attempts: int = LLM_STREAM_RETRY_ATTEMPTS,
    backoff_base: float = LLM_STREAM_RETRY_BACKOFF,
) -> AsyncIterator[str]:
    """Stream text deltas from an OpenAI-compatible ``/chat/completions`` SSE endpoint.

    Retries transient failures (429/5xx, transport errors) before the stream
    opens with exponential backoff. Non-transient errors (401/400/...) propagate
    immediately so the registry can fall through to another provider.
    """
    from pry.api.client import get_client  # lazy import avoids import cycles

    client = await get_client()
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    last_error: Exception | None = None
    started = False  # never retry after the first chunk has been yielded

    for attempt in range(retry_attempts + 1):
        try:
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=timeout_seconds
            ) as resp:
                if resp.status_code >= 400:
                    resp.raise_for_status()  # -> HTTPStatusError, caught below
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            started = True
                            yield content
                return
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in TRANSIENT_HTTP_STATUSES or attempt >= retry_attempts:
                raise
            last_error = e
        except httpx.TransportError as e:
            if started or attempt >= retry_attempts:
                raise
            last_error = e
        if attempt < retry_attempts:
            await asyncio.sleep(backoff_base * (2**attempt))

    if last_error is not None:
        raise last_error
