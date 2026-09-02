# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Concrete LLM provider implementations.

One module per provider (behavior unchanged); ``register_default_providers``
lives in :mod:`.defaults`. All provider classes are re-exported here so
existing ``from pry.intelligence.llm.providers import X`` imports work.
"""

from __future__ import annotations

from pry.intelligence.llm.base import LLMProvider

from .anthropic import AnthropicProvider
from .cerebras import CerebrasProvider
from .cohere import CohereProvider
from .deepseek import DeepSeekProvider
from .defaults import register_default_providers
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

__all__ = [
    "AnthropicProvider",
    "CerebrasProvider",
    "CohereProvider",
    "DeepSeekProvider",
    "GoogleProvider",
    "GroqProvider",
    "KiloCodeProvider",
    "KimiProvider",
    "LLMProvider",
    "MinimaxProvider",
    "MistralProvider",
    "NousProvider",
    "NvidiaProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenCodeZenProvider",
    "OpenRouterProvider",
    "SiliconFlowProvider",
    "ZaiProvider",
    "register_default_providers",
]
