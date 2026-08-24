# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""LLM provider registry with fallback chain, retry, and cost tracking.

AI-forward additions (2026-08-16):
- Per-provider retry with exponential backoff on transient failures (429/5xx/timeout)
  then fall through to the next provider in the configured order.
- Provider order is configurable via ``PRY_LLM_PROVIDER_ORDER`` (comma-separated);
  retry/timeouts via ``PRY_LLM_RETRY_MAX_ATTEMPTS``, ``PRY_LLM_RETRY_BASE_DELAY``,
  ``PRY_LLM_RETRY_MAX_DELAY``, and ``PRY_LLM_TIMEOUT_SECONDS`` (see base.py).
- ``complete_json`` for schema-validated JSON responses.
- ``stream_chat`` / ``stream_json`` SSE-style generators with provider fallback.
- Every call is recorded in ``llm_providers.base.cost_tracker`` (in-memory spend).
"""

import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from llm_providers.base import (
    TRANSIENT_HTTP_STATUSES,
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMRetryableError,
    ReferralConfig,
    attach_llm_metadata,
    cost_tracker,
    parse_json_response,
)
from pry.core.paths import PRY_DATA_DIR
from pry.engine.retry import BackoffStrategy, Jitter, RetryConfig, async_retry

logger = logging.getLogger(__name__)

USAGE_DIR = PRY_DATA_DIR / "llm_usage"
USAGE_DIR.mkdir(parents=True, exist_ok=True)


def _provider_order_from_env() -> list[str]:
    """Read the configured provider priority order from PRY_LLM_PROVIDER_ORDER."""
    raw = os.getenv("PRY_LLM_PROVIDER_ORDER", "")
    return [name.strip().lower() for name in raw.split(",") if name.strip()]


def _is_transient(exc: BaseException) -> bool:
    """Return True for transient LLM failures that warrant retry/fallback."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT_HTTP_STATUSES
    return False


class LLMRegistry:
    """Registry of LLM providers with fallback chain, cost tracking, and referral config."""

    def __init__(self, referral: ReferralConfig | None = None):
        self.providers: dict[str, LLMProvider] = {}
        self.referral = referral or ReferralConfig()
        self.fallback_chain: list[str] = []
        self.retry_config = RetryConfig(
            max_retries=int(os.getenv("PRY_LLM_RETRY_MAX_ATTEMPTS", "2")),
            base_delay=float(os.getenv("PRY_LLM_RETRY_BASE_DELAY", "0.5")),
            max_delay=float(os.getenv("PRY_LLM_RETRY_MAX_DELAY", "30")),
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=Jitter.FULL,
            retryable_exceptions=(LLMRetryableError,),
        )
        # Usage tracking
        self.usage: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "last_used": None,
            }
        )
        self._load_usage()

    def register(self, provider: LLMProvider) -> None:
        self.providers[provider.name] = provider
        if provider.name not in self.fallback_chain:
            self.fallback_chain.append(provider.name)
        logger.info("provider_registered", extra={"provider_name": provider.name})

    def set_fallback_chain(self, chain: list[str]) -> None:
        self.fallback_chain = chain

    def _names_for(self, provider_name: str, fallback: bool) -> list[str]:
        """Resolve the ordered provider names for a request."""
        if provider_name:
            return [provider_name]
        if fallback:
            return list(self.fallback_chain)
        return [self.fallback_chain[0]] if self.fallback_chain else []

    async def _execute(self, provider: LLMProvider, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Run a provider call with per-provider retry on transient failures."""

        async def guarded() -> Any:
            try:
                return await fn()
            except Exception as e:  # classify for retry
                if _is_transient(e):
                    raise LLMRetryableError(str(e)) from e
                raise

        return await async_retry(guarded, config=self.retry_config)

    def _finalize(self, response: LLMResponse, provider: LLMProvider) -> LLMResponse:
        # Caller sets response.latency_ms before calling this.
        response.cost_usd = provider.estimate_cost(response.input_tokens, response.output_tokens)
        response.referral_id = self.referral.program_id
        self._track(response)
        return response

    async def complete(
        self,
        prompt: str,
        system: str = "",
        provider_name: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: bool = True,
    ) -> LLMResponse:
        """Complete via specified provider or fallback chain, with retry+backoff.

        Transient failures (429/5xx/timeout) retry the same provider with
        exponential backoff (``self.retry_config``), then fall through to the
        next provider in the configured order.
        """
        names = self._names_for(provider_name, fallback)
        last_error = ""
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                start = time.time()

                async def _call(_provider: LLMProvider = provider) -> LLMResponse:
                    return await _provider.complete(prompt, system, max_tokens, temperature, model)

                response = await self._execute(provider, _call)
                response.latency_ms = int((time.time() - start) * 1000)
                self._finalize(response, provider)
                return response
            except Exception as e:  # noqa: BLE001 - LLM fallback must catch all errors
                last_error = str(e)
                logger.warning(
                    "llm_provider_failed", extra={"provider": name, "error": str(e)[:100]}
                )
                if not fallback:
                    break
        raise LLMError(f"All LLM providers failed. Last: {last_error}")

    async def complete_or_empty(
        self,
        prompt: str,
        system: str = "",
        provider_name: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: bool = True,
    ) -> LLMResponse:
        """Complete via LLM, returning an empty response on total failure.

        Use this at API boundaries where a 500 is worse than degraded output.
        """
        try:
            return await self.complete(
                prompt, system, provider_name, max_tokens, temperature, model, fallback
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("llm_complete_failed_all_providers", extra={"error": str(e)[:120]})
            return LLMResponse(
                text="",
                provider="none",
                model="",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
            )

    async def complete_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system: str = "",
        provider_name: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: dict[str, Any] | None = None,
        fallback_chain: bool = True,
    ) -> dict[str, Any]:
        """Complete and return schema-validated JSON via the fallback chain.

        - HTTP/transport failures retry per provider, then fall through to the
          next provider (like :meth:`complete`).
        - Malformed JSON from a provider returns ``fallback`` (safe value).
        - If every provider fails and ``fallback`` is given, returns it with an
          ``error`` key; otherwise raises :class:`LLMError`.
        """
        names = self._names_for(provider_name, fallback_chain)
        last_error = ""
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                start = time.time()

                async def _call(_provider: LLMProvider = provider) -> LLMResponse:
                    # Only pass model if explicitly provided (non-empty), otherwise let provider use its default
                    if model:
                        return await _provider.complete(
                            prompt, system, max_tokens, temperature, model
                        )
                    return await _provider.complete(prompt, system, max_tokens, temperature)

                response = await self._execute(provider, _call)
                response.latency_ms = int((time.time() - start) * 1000)
                self._finalize(response, provider)
                data = parse_json_response(response.text, schema, fallback=fallback)
                return attach_llm_metadata(data, response, provider)
            except Exception as e:  # noqa: BLE001 - LLM fallback must catch all errors
                last_error = str(e)
                logger.warning(
                    "llm_json_provider_failed", extra={"provider": name, "error": str(e)[:100]}
                )
                if not fallback_chain:
                    break
        if fallback is not None:
            result = dict(fallback)
            result.setdefault("error", f"LLM providers failed: {last_error[:200]}")
            return result
        raise LLMError(f"All LLM providers failed for JSON completion. Last: {last_error}")

    async def embed(self, text: str, provider_name: str = "", model: str = "") -> list[float]:
        names = [provider_name] if provider_name else list(self.fallback_chain)
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                return await provider.embed(text, model)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "embed_provider_failed", extra={"provider": name, "error": str(e)[:80]}
                )
        raise LLMError("All embedding providers failed")

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        provider_name: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: bool = True,
    ) -> AsyncIterator[str]:
        """Stream text deltas, falling through providers on pre-stream failure.

        Note: if a provider fails mid-stream, already-yielded chunks cannot be
        unsent; fallback only happens on failures before the first chunk.
        """
        names = self._names_for(provider_name, fallback)
        last_error = ""
        for name in names:
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                async for chunk in provider.stream_chat(
                    prompt, system, max_tokens, temperature, model
                ):
                    yield chunk
                return
            except Exception as e:  # stream fallback must catch all errors
                last_error = str(e)
                logger.warning(
                    "llm_stream_provider_failed", extra={"provider": name, "error": str(e)[:100]}
                )
                if not fallback:
                    raise
        if last_error:
            raise LLMError(f"All LLM providers failed streaming. Last: {last_error}")

    async def stream_json(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system: str = "",
        provider_name: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: str = "",
        fallback: dict[str, Any] | None = None,
        fallback_chain: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream deltas, then yield one parsed/coerced JSON dict.

        On total provider failure, yields ``fallback`` (with ``error``) when
        provided, otherwise re-raises the last error.
        """
        parts: list[str] = []
        last_error = ""
        try:
            async for delta in self.stream_chat(
                prompt, system, provider_name, max_tokens, temperature, model, fallback_chain
            ):
                parts.append(delta)
        except Exception as e:  # degrade to fallback on stream failure
            last_error = str(e)
            logger.warning("llm_stream_json_failed", extra={"error": str(e)[:120]})
            if fallback is not None:
                result = dict(fallback)
                result.setdefault("error", f"LLM stream failed: {last_error[:200]}")
                yield result
                return
            raise
        yield parse_json_response("".join(parts), schema, fallback=fallback)

    def _track(self, response: LLMResponse) -> None:
        u = self.usage[response.provider]
        u["calls"] += 1
        u["input_tokens"] += response.input_tokens
        u["output_tokens"] += response.output_tokens
        u["cost_usd"] += response.cost_usd
        u["last_used"] = datetime.now(UTC).isoformat()
        # In-memory spend accounting (callers can read LLM cost without disk).
        cost_tracker.record(response)
        # NEW: track in-app LLM usage as referral revenue
        # Best-effort by design: analytics/revenue tracking must NEVER fail
        # the primary LLM call (a missing table / DB outage here used to
        # propagate as "All LLM providers failed").
        try:
            from pry.commerce.referrals import ReferralTracker

            if not hasattr(self, "_referral_tracker"):
                self._referral_tracker = ReferralTracker()
            # Estimate revenue at 5% of user cost (typical affiliate share)
            self._referral_tracker.track_in_app_usage(response.provider, response.cost_usd * 0.05)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - metering must not break serving
            logger.debug("llm_referral_track_failed", extra={"error": str(e)[:160]})
        # Persist daily
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        path = USAGE_DIR / f"usage_{today}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": datetime.now(UTC).isoformat(),
                            "provider": response.provider,
                            "model": response.model,
                            "input_tokens": response.input_tokens,
                            "output_tokens": response.output_tokens,
                            "cost_usd": response.cost_usd,
                            "referral_id": response.referral_id,
                        }
                    )
                    + "\n"
                )
        except OSError as e:
            logger.warning("llm_usage_log_write_failed", extra={"error": str(e)[:160]})

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
            "cost_tracker": cost_tracker.stats(),
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
        # Apply configured provider priority order (PRY_LLM_PROVIDER_ORDER)
        order = _provider_order_from_env()
        if order:
            _registry.set_fallback_chain([p for p in order if p in _registry.providers])
    return _registry
