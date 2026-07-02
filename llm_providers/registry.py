# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""LLM provider registry with fallback chain and cost tracking."""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_providers.base import LLMProvider, LLMResponse, ReferralConfig

from paths import PRY_DATA_DIR
logger = logging.getLogger(__name__)

USAGE_DIR = PRY_DATA_DIR / "llm_usage"
USAGE_DIR.mkdir(parents=True, exist_ok=True)


class LLMRegistry:
    """Registry of LLM providers with fallback chain, cost tracking, and referral config."""

    def __init__(self, referral: ReferralConfig | None = None):
        self.providers: dict[str, LLMProvider] = {}
        self.referral = referral or ReferralConfig()
        self.fallback_chain: list[str] = []
        # Usage tracking
        self.usage: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "last_used": None,
        })
        self._load_usage()

    def register(self, provider: LLMProvider) -> None:
        self.providers[provider.name] = provider
        if provider.name not in self.fallback_chain:
            self.fallback_chain.append(provider.name)
        logger.info("provider_registered", extra={"provider_name": provider.name})

    def set_fallback_chain(self, chain: list[str]) -> None:
        self.fallback_chain = chain

    async def complete(self, prompt: str, system: str = "", provider_name: str = "",
                      max_tokens: int = 1024, temperature: float = 0.7, model: str = "",
                      fallback: bool = True) -> LLMResponse:
        """Complete via specified provider or fallback chain."""
        names = [provider_name] if provider_name else list(self.fallback_chain)
        if not fallback:
            names = [provider_name] if provider_name else [self.fallback_chain[0]] if self.fallback_chain else []

        last_error = ""
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                start = time.time()
                response = await provider.complete(prompt, system, max_tokens, temperature, model)
                response.latency_ms = int((time.time() - start) * 1000)
                response.cost_usd = provider.estimate_cost(response.input_tokens, response.output_tokens)
                response.referral_id = self.referral.program_id
                self._track(response)
                return response
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                logger.warning("llm_provider_failed",
                               extra={"provider": name, "error": str(e)[:100]})
                if not fallback:
                    break
        raise Exception(f"All LLM providers failed. Last: {last_error}")

    async def embed(self, text: str, provider_name: str = "", model: str = "") -> list[float]:
        names = [provider_name] if provider_name else list(self.fallback_chain)
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                return await provider.embed(text, model)
            except Exception as e:  # noqa: BLE001
                logger.warning("embed_provider_failed", extra={"provider": name, "error": str(e)[:80]})
        raise Exception("All embedding providers failed")

    def _track(self, response: LLMResponse) -> None:
        u = self.usage[response.provider]
        u["calls"] += 1
        u["input_tokens"] += response.input_tokens
        u["output_tokens"] += response.output_tokens
        u["cost_usd"] += response.cost_usd
        u["last_used"] = datetime.now(UTC).isoformat()
        # NEW: track in-app LLM usage as referral revenue
        try:
            from referrals import ReferralTracker
            if not hasattr(self, '_referral_tracker'):
                self._referral_tracker = ReferralTracker()
            # Estimate revenue at 5% of user cost (typical affiliate share)
            self._referral_tracker.track_in_app_usage(response.provider, response.cost_usd * 0.05)
        except ImportError:
            pass
        # Persist daily
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        path = USAGE_DIR / f"usage_{today}.jsonl"
        try:
            with open(path, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(UTC).isoformat(),
                    "provider": response.provider, "model": response.model,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": response.cost_usd,
                    "referral_id": response.referral_id,
                }) + "\n")
        except OSError:
            pass

    def _load_usage(self) -> None:
        for path in USAGE_DIR.glob("usage_*.jsonl"):
            try:
                for line in path.read_text().splitlines():
                    if line.strip():
                        r = json.loads(line)
                        prov = r.get("provider", "unknown")
                        u = self.usage[prov]
                        u["calls"] += 1
                        u["input_tokens"] += r.get("input_tokens", 0)
                        u["output_tokens"] += r.get("output_tokens", 0)
                        u["cost_usd"] += r.get("cost_usd", 0.0)
            except (json.JSONDecodeError, OSError):
                pass

    def get_stats(self) -> dict[str, Any]:
        return {
            "providers": {name: self.usage[p.name] for name, p in self.providers.items()},
            "referral": {
                "enabled": self.referral.enabled,
                "program_id": self.referral.program_id,
                "links": self.referral.referral_links,
            },
            "fallback_chain": self.fallback_chain,
        }


# Global registry
_registry: LLMRegistry | None = None


def get_registry() -> LLMRegistry:
    """Get or create the global LLM registry with default providers."""
    global _registry
    if _registry is None:
        _registry = LLMRegistry()
        # Register providers lazily (only if API keys are set)
        from llm_providers.providers import register_default_providers
        register_default_providers(_registry)
    return _registry
