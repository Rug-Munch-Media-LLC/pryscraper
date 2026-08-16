"""Retry/backoff helpers for Pry scrapers.

Provides configurable async retry with exponential backoff, jitter, and
circuit-breaker integration so external service calls degrade gracefully.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import enum
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import resilience

# SystemRandom: crypto-grade entropy for backoff jitter.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

# ── Types ─────────────────────────────────────────────────────────
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class BackoffStrategy(enum.StrEnum):
    """Available backoff strategies for retry delays."""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"


class Jitter(enum.StrEnum):
    """Jitter modes for retry delays.

    - NONE: no jitter, pure backoff.
    - FULL: random uniform between 0 and the computed delay.
    - EQUAL: the delay is halved and jitter is applied to each half.
    - DECORRELATED: previous_delay * random(1, 3), capped at max_delay.
    """

    NONE = "none"
    FULL = "full"
    EQUAL = "equal"
    DECORRELATED = "decorrelated"


# ── Config ────────────────────────────────────────────────────────
@dataclass
class RetryConfig:
    """Configuration for async retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts (does not include the
            initial call). Default 3 means up to 1 initial + 3 retries = 4
            total attempts.
        max_time: Maximum wall-clock seconds to keep retrying. 0 = no limit.
        base_delay: Base delay in seconds for backoff calculations.
        max_delay: Maximum delay in seconds between retries.
        strategy: Backoff strategy (exponential, linear, fixed).
        jitter: Jitter mode (none, full, equal, decorrelated).
        retryable_exceptions: Tuple of exception types that trigger retry.
            If None, all exceptions are retried.
        circuit_breaker: Name of a ResilienceRegistry circuit breaker to
            consult before retrying. If the breaker is open, retry is skipped
            and the last error is re-raised. None = no circuit breaker.
    """

    max_retries: int = 3
    max_time: float = 0.0
    base_delay: float = 1.0
    max_delay: float = 60.0
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    jitter: Jitter = Jitter.FULL
    retryable_exceptions: tuple[type[Exception], ...] | None = None
    circuit_breaker: str | None = None


# ── Wait calculators ──────────────────────────────────────────────
def _calculate_base_delay(attempt: int, config: RetryConfig) -> float:
    """Compute the un-jittered, max_delay-capped delay for an attempt."""
    if config.strategy == BackoffStrategy.FIXED:
        delay = config.base_delay
    elif config.strategy == BackoffStrategy.LINEAR:
        delay = config.base_delay * (attempt + 1)
    else:  # EXPONENTIAL
        delay = config.base_delay * (2**attempt)

    return min(delay, config.max_delay)


def _calculate_delay(
    attempt: int,
    config: RetryConfig,
    *,
    previous_delay: float = 0.0,
) -> float:
    """Compute the final (jittered) delay for the given attempt number."""
    base = _calculate_base_delay(attempt, config)
    return _apply_jitter(
        base, config.jitter, previous_delay=previous_delay, max_delay=config.max_delay
    )


def _apply_jitter(
    delay: float,
    mode: Jitter,
    previous_delay: float = 0.0,
    max_delay: float = 60.0,
) -> float:
    """Apply jitter to a delay value.

    ``previous_delay`` must be the *un-jittered* previous base delay — passing
    an already-jittered value here would double-jitter the decorrelated mode.
    """
    if mode == Jitter.NONE:
        return delay
    if mode == Jitter.FULL:
        return _RNG.uniform(0, delay)
    if mode == Jitter.EQUAL:
        half = delay / 2.0
        return half + _RNG.uniform(0, half)
    if mode == Jitter.DECORRELATED:
        if previous_delay <= 0:
            return delay
        # Cap at the caller's configured max_delay, not a hardcoded 60s.
        return min(previous_delay * _RNG.uniform(1, 3), max_delay)
    return delay


# ── Public retry helpers ──────────────────────────────────────────
async def async_retry(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Call an async function with configurable retry and backoff.

    Args:
        fn: Async function to call.
        *args: Positional arguments passed to fn.
        config: Retry configuration. If None, uses defaults (3 retries,
            exponential backoff, full jitter).
        **kwargs: Keyword arguments passed to fn.

    Returns:
        The result of fn(*args, **kwargs) on success.

    Raises:
        The last exception raised by fn if all retries are exhausted, or
        if a non-retryable exception (not in config.retryable_exceptions)
        is raised.
    """
    cfg = config or RetryConfig()
    last_exc: Exception | None = None
    start_time = time.monotonic()
    previous_delay = 0.0

    # The first call is the initial attempt, not a retry.
    total_attempts = cfg.max_retries + 1

    for attempt in range(total_attempts):
        # If a circuit breaker is configured and open, skip immediately.
        if cfg.circuit_breaker and not resilience.registry.is_service_allowed(cfg.circuit_breaker):
            logger.debug(
                "retry_circuit_open",
                extra={
                    "service": cfg.circuit_breaker,
                    "fn": fn.__name__,
                    "attempt": attempt,
                },
            )
            if last_exc is not None:
                raise last_exc
            raise RuntimeError(
                f"Circuit breaker '{cfg.circuit_breaker}' is open \u2014 retry skipped"
            )

        try:
            result = await fn(*args, **kwargs)
            # Record success to the circuit breaker.
            if cfg.circuit_breaker:
                resilience.registry.record_service_result(cfg.circuit_breaker, True)
            return result
        except Exception as e:
            last_exc = e

            # Record failure to the circuit breaker.
            if cfg.circuit_breaker:
                resilience.registry.record_service_result(cfg.circuit_breaker, False)

            # Check if this exception type is retryable.
            if cfg.retryable_exceptions is not None and not isinstance(e, cfg.retryable_exceptions):
                raise

            # If this was the last attempt, break out to re-raise.
            if attempt >= cfg.max_retries:
                break

            # Check max wall-clock time.
            if cfg.max_time > 0 and (time.monotonic() - start_time) >= cfg.max_time:
                logger.warning(
                    "retry_max_time_exceeded",
                    extra={
                        "fn": fn.__name__,
                        "max_time": cfg.max_time,
                        "attempts": attempt + 1,
                    },
                )
                break

            # Wait before next attempt.
            # Track the *un-jittered* base delay so the decorrelated jitter
            # mode does not re-jitter an already-jittered value.
            base_delay = _calculate_base_delay(attempt, cfg)
            delay = _apply_jitter(
                base_delay,
                cfg.jitter,
                previous_delay=previous_delay,
                max_delay=cfg.max_delay,
            )
            previous_delay = base_delay
            logger.info(
                "retry_waiting",
                extra={
                    "fn": fn.__name__,
                    "attempt": attempt + 1,
                    "max_retries": cfg.max_retries,
                    "delay_seconds": round(delay, 2),
                    "error": str(e)[:80],
                },
            )
            await asyncio.sleep(delay)

    # All retries exhausted.
    if last_exc is not None:
        raise last_exc

    raise RuntimeError("retry_exhausted_no_exception")


def make_retry_decorator(
    config: RetryConfig | None = None,
) -> Callable[[F], F]:
    """Create a decorator that wraps an async function with retry logic.

    Example:
        @make_retry_decorator(RetryConfig(max_retries=5, base_delay=0.5))
        async def fetch_data(url: str) -> dict:
            ...
    """
    cfg = config or RetryConfig()

    def decorator(fn: F) -> F:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await async_retry(fn, *args, config=cfg, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__qualname__ = getattr(fn, "__qualname__", fn.__name__)
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = getattr(fn, "__module__", "")
        return wrapper  # type: ignore[return-value]

    return decorator
