"""Pry — LLM client core: errors, response/config dataclasses, provider ABC, cost tracking.

Split out of ``base.py`` (2026-09-06) — see ``base.py`` for the re-export facade.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pry.intelligence.llm.base_extract import attach_llm_metadata, parse_json_response

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
        """Stream deltas, buffer, then yield the parsed/coerced JSON dict."""
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
