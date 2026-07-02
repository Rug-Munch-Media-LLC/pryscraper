"""Pry — LLM Provider abstraction with referral revenue tracking.
Supports pluggable providers: OpenAI, Anthropic, Google, Cohere, Mistral, Ollama, OpenRouter.
Includes referral/affiliate link tracking for revenue sharing."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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
            from referrals import PROVIDER_CATALOG

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

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1000) * self.cost_per_1k_input + (
            output_tokens / 1000
        ) * self.cost_per_1k_output
