"""OTel bootstrap gate — disabled means no exporter, enabled is non-blocking.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from pry.core import otel_setup

_EMPTY = {"OTEL_ENABLED": "", "OTEL_EXPORTER_OTLP_ENDPOINT": ""}


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    with patch.object(otel_setup, "_initialised", False), patch.dict(os.environ, _EMPTY):
        yield
    otel_setup._initialised = False


def test_disabled_by_default_is_noop() -> None:
    called: list[Any] = []

    def _boom(*a: Any, **k: Any) -> Any:
        called.append(a)
        raise AssertionError("provider must not be built when OTel is unset")

    with patch.object(otel_setup, "_build_provider", _boom):
        assert otel_setup.is_enabled() is False
        assert otel_setup.setup_telemetry() is False
    assert called == []


def test_endpoint_alone_enables_tracing() -> None:
    with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318/v1/traces"}):
        assert otel_setup.is_enabled() is True


def test_missing_otlp_extra_does_not_block_startup() -> None:
    env = {
        "OTEL_ENABLED": "1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318/v1/traces",
    }
    with (
        patch.dict(os.environ, env),
        patch.object(otel_setup, "_build_provider", lambda service_name: None),
    ):
        assert otel_setup.setup_telemetry() is False


def test_provider_failure_never_raises() -> None:
    def _raise(*a: Any, **k: Any) -> Any:
        raise RuntimeError("collector down")

    with (
        patch.dict(os.environ, {"OTEL_ENABLED": "1"}),
        patch.object(otel_setup, "_build_provider", _raise),
    ):
        assert otel_setup.setup_telemetry() is False


def test_batch_processor_used_for_otlp() -> None:
    """OTLP export must be batched so startup never waits on a collector."""
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318/v1/traces"}):
        provider = otel_setup._build_provider("pry-test")
    assert provider is not None
    processors = list(provider._active_span_processor._span_processors)
    assert any(isinstance(p, BatchSpanProcessor) for p in processors)
