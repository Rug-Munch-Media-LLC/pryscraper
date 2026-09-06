"""Pry — LLM Provider abstraction with referral revenue tracking.

Thin re-export facade (split 2026-09-06). Implementation lives in:

- ``base_client``    — errors, response/config dataclasses, provider ABC, cost tracking
- ``base_extract``   — fence stripping, schema coercion, JSON parsing, metadata attach
- ``base_streaming`` — OpenAI/OpenRouter-compatible SSE streaming helper

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

from pry.intelligence.llm.base_client import (
    LLM_STREAM_RETRY_ATTEMPTS,
    LLM_STREAM_RETRY_BACKOFF,
    LLM_TIMEOUT_SECONDS,
    TRANSIENT_HTTP_STATUSES,
    LLMCostTracker,
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMRetryableError,
    ReferralConfig,
    cost_tracker,
)
from pry.intelligence.llm.base_extract import (
    attach_llm_metadata,
    coerce_to_schema,
    parse_json_response,
    strip_fences,
)
from pry.intelligence.llm.base_streaming import _stream_openai_compatible

__all__ = [
    "LLM_STREAM_RETRY_ATTEMPTS",
    "LLM_STREAM_RETRY_BACKOFF",
    "LLM_TIMEOUT_SECONDS",
    "TRANSIENT_HTTP_STATUSES",
    "LLMCostTracker",
    "LLMError",
    "LLMProvider",
    "LLMResponse",
    "LLMRetryableError",
    "ReferralConfig",
    "_stream_openai_compatible",
    "attach_llm_metadata",
    "coerce_to_schema",
    "cost_tracker",
    "parse_json_response",
    "strip_fences",
]
