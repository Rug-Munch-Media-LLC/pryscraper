"""Pry — LLM Provider abstraction with referral revenue tracking.
Supports pluggable providers: OpenAI, Anthropic, Google, Cohere, Mistral, Ollama, OpenRouter.
Includes referral/affiliate link tracking for revenue sharing.

AI-forward helpers added 2026-08-16:
- ``complete_json`` — schema-validated JSON completion (fence-stripping + coercion)
- ``parse_json_response`` / ``coerce_to_schema`` — shared JSON parsing/coercion
- ``LLMCostTracker`` — lightweight in-memory per-call token/usage accounting
- ``stream_chat`` / ``stream_json`` — SSE-style async generators for streaming
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Transient HTTP statuses that warrant retry / provider fallback.
TRANSIENT_HTTP_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Settings-driven LLM knobs (PRY_* env vars; settings.py owns the object model,
# these live here so providers don't need to reach into settings).
LLM_TIMEOUT_SECONDS = float(os.getenv("PRY_LLM_TIMEOUT_SECONDS", "60"))
LLM_STREAM_RETRY_ATTEMPTS = int(os.getenv("PRY_LLM_STREAM_RETRY_ATTEMPTS", "2"))
LLM_STREAM_RETRY_BACKOFF = float(os.getenv("PRY_LLM_STREAM_RETRY_BACKOFF", "0.5"))


class LLMError(Exception):
    """Base error for the LLM layer."""


class LLMRetryableError(LLMError):
    """Transient LLM failure (429/5xx/timeout) — retry or fall through."""


@dataclass
class LLMResponse:
    """Standard response from any LLM provider."""

    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    referral_id: str = ""
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReferralConfig:
    """Referral/affiliate config for revenue sharing."""

    enabled: bool = True
    program_id: str = "pry-default"
    # Provider-specific referral links (with our affiliate ID)
    referral_links: dict[str, str] = field(default_factory=dict)
    # NEW: link to the full provider catalog
    catalog: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.referral_links:
            from pry.commerce.referrals import PROVIDER_CATALOG

            for _category, providers in PROVIDER_CATALOG.items():
                for p in providers:
                    self.referral_links[p["tag"]] = p["url"]
            self.catalog = PROVIDER_CATALOG


def strip_fences(text: str) -> str:
    """Strip markdown code fences that LLMs commonly wrap JSON in."""
    t = text.strip()
    if t.startswith("```json"):
        t = t[len("```json") :]
    elif t.startswith("```"):
        t = t[len("```") :]
    if t.endswith("```"):
        t = t[: -len("```")]
    return t.strip()


# ── Schema coercion ──────────────────────────────────────────────


def _to_int(value: Any) -> Any:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        return int(float(value))
    except (TypeError, ValueError):
        return value


def _to_float(value: Any) -> Any:
    try:
        if isinstance(value, float):
            return value
        return float(value)
    except (TypeError, ValueError):
        return value


def _to_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return value


def _to_list(value: Any) -> Any:
    # Never guess-split strings — a wrong split is worse than leaving data intact.
    return value


_SCALAR_COERCERS: dict[str, Callable[[Any], Any]] = {
    "str": str,
    "int": _to_int,
    "float": _to_float,
    "bool": _to_bool,
    "list": _to_list,
    "dict": lambda v: v,
    "any": lambda v: v,
}


def coerce_to_schema(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Coerce parsed JSON to a schema, filling missing keys with None.

    Schema format (lightweight, no JSON-Schema dependency):
        {"risk_level": "green|yellow|red", "score": "int", "tags": {"type": "list"},
         "nested": {"sub": "float"}}

    Rules:
    - Scalar type strings ("str", "int", "float", "bool", "list", "dict", "any")
      coerce the value; uncoercible values are left as-is (never crash).
    - "a|b|c" is an enum — values not in the list are left as-is.
    - A nested dict spec is applied recursively.
    - ``{"type": "list", "items": {...}}`` coerces list members.
    - Missing keys are filled with ``None``; unknown keys are preserved.
    """
    for key, spec in schema.items():
        if key not in data:
            data[key] = None
            continue
        value = data[key]
        if isinstance(spec, dict):
            if spec.get("type") == "list":
                items = spec.get("items")
                if isinstance(value, list) and isinstance(items, dict):
                    data[key] = [
                        coerce_to_schema(item, items) if isinstance(item, dict) else item
                        for item in value
                    ]
                elif value is not None and not isinstance(value, list):
                    data[key] = _SCALAR_COERCERS.get("list", lambda v: v)(value)
            else:
                # Nested object schema
                if isinstance(value, dict):
                    data[key] = coerce_to_schema(dict(value), spec)
                elif value is not None:
                    data[key] = _SCALAR_COERCERS.get("dict", lambda v: v)(value)
            continue
        if not isinstance(spec, str):
            continue
        if "|" in spec:
            allowed = {part.strip() for part in spec.split("|")}
            if isinstance(value, str) and value.strip().lower() in {a.lower() for a in allowed}:
                data[key] = value.strip()
            # Non-matching enum values are preserved for callers to judge.
            continue
        coercer = _SCALAR_COERCERS.get(spec)
        if coercer is not None and value is not None:
            data[key] = coercer(value)
    return data


def parse_json_response(
    text: str,
    schema: dict[str, Any] | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse an LLM response as JSON, strip fences, coerce to schema.

    Returns ``dict(fallback or {})`` on any parse failure or non-dict payload —
    the "safe fallback" contract so callers never crash on malformed output.
    """
    try:
        data = json.loads(strip_fences(text))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("llm_json_parse_failed", extra={"error": str(e)[:120]})
        return dict(fallback or {})
    if not isinstance(data, dict):
        logger.warning("llm_json_not_object")
        return dict(fallback or {})
    if schema:
        data = coerce_to_schema(data, schema)
    return data


def attach_llm_metadata(
    data: dict[str, Any], response: LLMResponse, provider: "LLMProvider"
) -> dict[str, Any]:
    """Attach provider/cost metadata to a parsed JSON result (setdefault, no overwrite)."""
    data.setdefault("llm_provider", response.provider or provider.name)
    data.setdefault(
        "llm_cost_usd",
        round(provider.estimate_cost(response.input_tokens, response.output_tokens), 6),
    )
    data.setdefault("llm_input_tokens", response.input_tokens)
    data.setdefault("llm_output_tokens", response.output_tokens)
    return data


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = ""
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    referral_url: str = ""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
    ) -> LLMResponse:
        """Send completion request to provider."""
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str, model: str = "") -> list[float]:
        """Generate embedding for text."""
        raise NotImplementedError

    async def complete_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a completion and return validated JSON (fence-stripped, coerced).

        On JSON parse failure returns ``fallback`` (default ``{}``) so callers
        get a safe value instead of an exception. HTTP/transport errors are
        re-raised — the registry handles retry/fallback for those.
        """
        response = await self.complete(prompt, system, max_tokens, temperature, model)
        data = parse_json_response(response.text, schema, fallback=fallback)
        return attach_llm_metadata(data, response, self)

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas.

        Default implementation buffers a non-streaming completion and yields it
        as a single chunk; OpenAI/OpenRouter override with real SSE streaming.
        """
        response = await self.complete(prompt, system, max_tokens, temperature, model)
        yield response.text

    async def stream_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream deltas, buffer, then yield the parsed/coerced JSON dict once.

        Ideal for SSE endpoints that emit a single ``data: {json}`` event after
        token streaming, e.g. vision/extract streams.
        """
        parts: list[str] = []
        async for delta in self.stream_chat(
            prompt, system, max_tokens, temperature, model, **kwargs
        ):
            parts.append(delta)
        yield parse_json_response("".join(parts), schema, fallback=fallback)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1000) * self.cost_per_1k_input + (
            output_tokens / 1000
        ) * self.cost_per_1k_output


# ── Cost tracking ─────────────────────────────────────────────────


@dataclass
class _UsageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class LLMCostTracker:
    """Lightweight in-memory per-call token/usage accounting.

    Records every LLMResponse through the registry so callers can surface
    LLM spend without querying the usage JSONL. Optional per-call logging.
    """

    def __init__(self, log: bool = False) -> None:
        self.log = log
        self._by_provider: dict[str, _UsageTotals] = defaultdict(_UsageTotals)

    def record(self, response: LLMResponse) -> None:
        """Record a single call."""
        provider = response.provider or "unknown"
        totals = self._by_provider[provider]
        totals.calls += 1
        totals.input_tokens += response.input_tokens
        totals.output_tokens += response.output_tokens
        totals.cost_usd += response.cost_usd
        if self.log:
            logger.info(
                "llm_cost_recorded",
                extra={
                    "provider": provider,
                    "model": response.model,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": round(response.cost_usd, 6),
                },
            )

    def stats(self) -> dict[str, Any]:
        """Return aggregate + per-provider totals."""
        total = _UsageTotals()
        per_provider: dict[str, dict[str, Any]] = {}
        for provider, t in self._by_provider.items():
            per_provider[provider] = {
                "calls": t.calls,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cost_usd": round(t.cost_usd, 6),
            }
            total.calls += t.calls
            total.input_tokens += t.input_tokens
            total.output_tokens += t.output_tokens
            total.cost_usd += t.cost_usd
        return {
            "calls": total.calls,
            "input_tokens": total.input_tokens,
            "output_tokens": total.output_tokens,
            "cost_usd": round(total.cost_usd, 6),
            "per_provider": per_provider,
        }

    def reset(self) -> None:
        """Clear all recorded usage."""
        self._by_provider.clear()


# Module-level singleton callers use to read LLM spend.
cost_tracker = LLMCostTracker()


# ── OpenAI/OpenRouter-compatible SSE streaming ────────────────────


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
