"""Tests for retry/backoff helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import resilience
from retry import (
    BackoffStrategy,
    Jitter,
    RetryConfig,
    _apply_jitter,
    _calculate_delay,
    async_retry,
    make_retry_decorator,
)


class TestBackoffStrategy:
    def test_enum_values(self) -> None:
        assert BackoffStrategy.EXPONENTIAL.value == "exponential"
        assert BackoffStrategy.LINEAR.value == "linear"
        assert BackoffStrategy.FIXED.value == "fixed"


class TestJitter:
    def test_enum_values(self) -> None:
        assert Jitter.NONE.value == "none"
        assert Jitter.FULL.value == "full"
        assert Jitter.EQUAL.value == "equal"
        assert Jitter.DECORRELATED.value == "decorrelated"


class TestRetryConfig:
    def test_defaults(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.strategy == BackoffStrategy.EXPONENTIAL
        assert cfg.jitter == Jitter.FULL
        assert cfg.circuit_breaker is None

    def test_custom_values(self) -> None:
        cfg = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=30.0,
            strategy=BackoffStrategy.LINEAR,
            jitter=Jitter.NONE,
            circuit_breaker="flaresolverr",
        )
        assert cfg.max_retries == 5
        assert cfg.base_delay == 0.5
        assert cfg.max_delay == 30.0
        assert cfg.strategy == BackoffStrategy.LINEAR
        assert cfg.jitter == Jitter.NONE
        assert cfg.circuit_breaker == "flaresolverr"


class TestCalculateDelay:
    def test_exponential_doubles(self) -> None:
        cfg = RetryConfig(strategy=BackoffStrategy.EXPONENTIAL, jitter=Jitter.NONE)
        assert _calculate_delay(0, cfg) == 1.0
        assert _calculate_delay(1, cfg) == 2.0
        assert _calculate_delay(2, cfg) == 4.0
        assert _calculate_delay(3, cfg) == 8.0

    def test_exponential_capped_at_max(self) -> None:
        cfg = RetryConfig(
            strategy=BackoffStrategy.EXPONENTIAL,
            base_delay=1.0,
            max_delay=5.0,
            jitter=Jitter.NONE,
        )
        assert _calculate_delay(0, cfg) == 1.0
        assert _calculate_delay(1, cfg) == 2.0
        assert _calculate_delay(2, cfg) == 4.0
        assert _calculate_delay(3, cfg) == 5.0

    def test_linear_increases_by_base(self) -> None:
        cfg = RetryConfig(strategy=BackoffStrategy.LINEAR, jitter=Jitter.NONE)
        assert _calculate_delay(0, cfg) == 1.0
        assert _calculate_delay(1, cfg) == 2.0
        assert _calculate_delay(2, cfg) == 3.0

    def test_fixed_always_base(self) -> None:
        cfg = RetryConfig(strategy=BackoffStrategy.FIXED, jitter=Jitter.NONE)
        assert _calculate_delay(0, cfg) == 1.0
        assert _calculate_delay(5, cfg) == 1.0
        assert _calculate_delay(99, cfg) == 1.0

    def test_linear_capped(self) -> None:
        cfg = RetryConfig(
            strategy=BackoffStrategy.LINEAR,
            base_delay=10.0,
            max_delay=25.0,
            jitter=Jitter.NONE,
        )
        assert _calculate_delay(0, cfg) == 10.0
        assert _calculate_delay(1, cfg) == 20.0
        assert _calculate_delay(2, cfg) == 25.0


class TestJitterApplication:
    def test_none_returns_delay(self) -> None:
        assert _apply_jitter(5.0, Jitter.NONE) == 5.0

    def test_full_is_between_0_and_delay(self) -> None:
        for _ in range(50):
            result = _apply_jitter(10.0, Jitter.FULL)
            assert 0 <= result <= 10.0

    def test_equal_is_positive(self) -> None:
        for _ in range(50):
            result = _apply_jitter(10.0, Jitter.EQUAL)
            assert 5 <= result <= 10.0

    def test_decorrelated_uses_previous(self) -> None:
        for _ in range(50):
            result = _apply_jitter(5.0, Jitter.DECORRELATED, previous_delay=2.0)
            assert 2.0 <= result <= 6.0

    def test_decorrelated_without_previous_returns_delay(self) -> None:
        assert _apply_jitter(5.0, Jitter.DECORRELATED, previous_delay=0) == 5.0


class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        fn = AsyncMock(return_value="ok")
        result = await async_retry(fn, config=RetryConfig(jitter=Jitter.NONE))
        assert result == "ok"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_after_retries(self) -> None:
        fn = AsyncMock(side_effect=[ValueError("fail1"), ValueError("fail2"), "ok"])
        result = await async_retry(
            fn,
            config=RetryConfig(max_retries=3, base_delay=0.01, jitter=Jitter.NONE),
        )
        assert result == "ok"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises(self) -> None:
        fn = AsyncMock(side_effect=ValueError("always fails"))
        with pytest.raises(ValueError, match="always fails"):
            await async_retry(
                fn,
                config=RetryConfig(max_retries=2, base_delay=0.01, jitter=Jitter.NONE),
            )
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception_passthrough(self) -> None:
        fn = AsyncMock(side_effect=TypeError("not retryable"))
        cfg = RetryConfig(
            retryable_exceptions=(ValueError,),
            base_delay=0.01,
            jitter=Jitter.NONE,
        )
        with pytest.raises(TypeError, match="not retryable"):
            await async_retry(fn, config=cfg)
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retryable_exception_does_retry(self) -> None:
        fn = AsyncMock(side_effect=[ValueError("retry"), "ok"])
        cfg = RetryConfig(
            max_retries=2,
            retryable_exceptions=(ValueError,),
            base_delay=0.01,
            jitter=Jitter.NONE,
        )
        result = await async_retry(fn, config=cfg)
        assert result == "ok"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_max_time_exceeded_stops_retrying(self) -> None:
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(
            max_retries=5,
            max_time=0.05,
            base_delay=0.1,
            jitter=Jitter.NONE,
        )
        with pytest.raises(ValueError):
            await async_retry(fn, config=cfg)
        assert fn.call_count < 6

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_retry(self) -> None:
        name = "cb_block_utest"
        cb = resilience.registry.breaker(name)
        cb.failure_threshold = 1
        resilience.registry.record_service_result(name, False)
        assert resilience.registry.is_service_allowed(name) is False

        fn = AsyncMock(side_effect=ConnectionError("fail"))
        cfg = RetryConfig(
            max_retries=3,
            circuit_breaker=name,
            base_delay=0.01,
            jitter=Jitter.NONE,
        )
        with pytest.raises(RuntimeError, match="Circuit breaker"):
            await async_retry(fn, config=cfg)
        assert fn.call_count == 0
        del resilience.registry.breakers[name]

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(self) -> None:
        name = "cb_success_utest"
        fn = AsyncMock(return_value="ok")
        cfg = RetryConfig(
            max_retries=1,
            circuit_breaker=name,
            base_delay=0.01,
            jitter=Jitter.NONE,
        )
        result = await async_retry(fn, config=cfg)
        assert result == "ok"
        cb = resilience.registry.breaker(name)
        assert cb.successes >= 1
        del resilience.registry.breakers[name]

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure(self) -> None:
        name = "cb_fail_utest"
        fn = AsyncMock(side_effect=ConnectionError("fail"))
        cfg = RetryConfig(
            max_retries=1,
            circuit_breaker=name,
            base_delay=0.01,
            jitter=Jitter.NONE,
        )
        with pytest.raises(ConnectionError):
            await async_retry(fn, config=cfg)
        cb = resilience.registry.breaker(name)
        assert cb.failures >= 1
        del resilience.registry.breakers[name]

    @pytest.mark.asyncio
    async def test_default_config_works(self) -> None:
        fn = AsyncMock(return_value="ok")
        result = await async_retry(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self) -> None:
        fn = AsyncMock(return_value="ok")

        async def target(url: str, *, timeout: int = 30) -> str:
            fn(url, timeout=timeout)
            return "ok"

        await async_retry(
            target,
            "https://example.com",
            config=RetryConfig(jitter=Jitter.NONE),
            timeout=10,
        )
        fn.assert_called_once_with("https://example.com", timeout=10)


class TestMakeRetryDecorator:
    @pytest.mark.asyncio
    async def test_decorator_retries_on_failure(self) -> None:
        call_count = 0

        @make_retry_decorator(RetryConfig(max_retries=2, base_delay=0.01, jitter=Jitter.NONE))
        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        result = await flaky_func()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_decorator_preserves_metadata(self) -> None:
        @make_retry_decorator()
        async def my_func() -> str:
            """My docstring."""
            return "ok"

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "My docstring."
