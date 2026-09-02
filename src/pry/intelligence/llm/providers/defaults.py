# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Default provider registration for the LLM registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .anthropic import AnthropicProvider
from .cerebras import CerebrasProvider
from .cohere import CohereProvider
from .deepseek import DeepSeekProvider
from .google import GoogleProvider
from .groq import GroqProvider
from .kilocode import KiloCodeProvider
from .kimi import KimiProvider
from .local import OllamaProvider
from .minimax import MinimaxProvider
from .mistral import MistralProvider
from .nous import NousProvider
from .nvidia import NvidiaProvider
from .openai import OpenAIProvider
from .opencode_zen import OpenCodeZenProvider
from .openrouter import OpenRouterProvider
from .siliconflow import SiliconFlowProvider
from .zai import ZaiProvider

if TYPE_CHECKING:
    from pry.intelligence.llm.registry import LLMRegistry


def register_default_providers(registry: LLMRegistry) -> None:
    """Register all providers whose API keys are set in environment."""
    from pry.core.settings import settings

    # BYOK (bring your own key): one account per provider. Consumers set
    # PRY_<PROVIDER>_API_KEY (or the provider's standard env var, which each
    # provider class falls back to). Multi-account fan-out is a deployment
    # concern, not a product concern — run multiple instances or a router.
    api_key_map = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.gemini_api_key,
        "cohere": settings.cohere_api_key,
        "mistral": settings.mistral_api_key,
        "openrouter": settings.openrouter_api_key,
        "kilocode": settings.kilocode_api_key,
        "deepseek": settings.deepseek_api_key,
        "groq": settings.groq_api_key,
        "kimi": settings.kimi_api_key,
        "nvidia": settings.nvidia_api_key,
        "nous": settings.nous_api_key,
        "zai": settings.zai_api_key,
        "cerebras": settings.cerebras_api_key,
        "minimax": settings.minimax_api_key,
        "siliconflow": settings.siliconflow_api_key,
        "opencode_zen": settings.opencode_zen_api_key,
    }
    provider_classes = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "cohere": CohereProvider,
        "mistral": MistralProvider,
        "openrouter": OpenRouterProvider,
        "kilocode": KiloCodeProvider,
        "deepseek": DeepSeekProvider,
        "groq": GroqProvider,
        "kimi": KimiProvider,
        "nvidia": NvidiaProvider,
        "nous": NousProvider,
        "zai": ZaiProvider,
        "cerebras": CerebrasProvider,
        "minimax": MinimaxProvider,
        "siliconflow": SiliconFlowProvider,
        "opencode_zen": OpenCodeZenProvider,
    }
    for name, cls in provider_classes.items():
        key = api_key_map.get(name)
        if key:
            registry.register(cls(api_key=key))
    # Ollama is always available if running locally (free, private)
    registry.register(OllamaProvider())
