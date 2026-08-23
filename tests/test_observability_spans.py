# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for audit wins #15/#19: OTel span helper + metric cardinality fix."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import middleware as mw_module
from observability import get_tracer, span


class TestSpanHelper:
    def test_get_tracer_returns_when_otel_available(self) -> None:
        # OTel IS installed in the dev venv; helper must return a tracer.
        tracer = get_tracer()
        assert tracer is not None

    def test_span_yields_and_sets_attributes(self) -> None:
        with span("test.span", {"pry.tier": "direct", "skip": None}) as s:
            assert s is not None  # OTel installed -> real span object
            s.set_attribute("extra", "v")

    def test_span_records_exception_and_reraises(self) -> None:
        with pytest.raises(RuntimeError, match="boom"), span("test.span.fail"):
            raise RuntimeError("boom")


class TestMetricCardinality:
    """Route TEMPLATE must be the metric label, never the raw path (#19)."""

    def test_route_template_used_as_endpoint_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mw_module.settings, "api_key", "")
        recorded: list[tuple[str, str, str]] = []
        latency_seen: list[str] = []

        class _FakeCounter:
            def labels(self, method: str, endpoint: str, status: str):
                recorded.append((method, endpoint, status))

                class _M:
                    def inc(self) -> None: ...

                return _M()

        class _FakeHistogram:
            def labels(self, endpoint: str):
                latency_seen.append(endpoint)

                class _O:
                    def observe(self, v: float) -> None: ...

                return _O()

        monkeypatch.setattr(mw_module, "REQUEST_COUNT", _FakeCounter())
        monkeypatch.setattr(mw_module, "REQUEST_LATENCY", _FakeHistogram())

        a = FastAPI()
        a.add_middleware(mw_module.PryHttpMiddleware)

        @a.get("/v1/job/{job_id}")
        async def job(job_id: str) -> dict[str, str]:
            return {"id": job_id}

        client = TestClient(a, client=("127.0.0.1", 5000))
        client.get("/v1/job/abc-123")
        client.get("/v1/job/completely-different-id")

        # Both requests land on ONE template series, not two path series.
        endpoints = [e for _, e, _ in recorded]
        assert endpoints == ["/v1/job/{job_id}", "/v1/job/{job_id}"]
        assert latency_seen == ["/v1/job/{job_id}", "/v1/job/{job_id}"]

    def test_unmatched_404_buckets_under_fixed_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mw_module.settings, "api_key", "")
        recorded: list[str] = []

        class _FakeCounter:
            def labels(self, method: str, endpoint: str, status: str):
                recorded.append(endpoint)

                class _M:
                    def inc(self) -> None: ...

                return _M()

        class _FakeHistogram:
            def labels(self, endpoint: str):
                class _O:
                    def observe(self, v: float) -> None: ...

                return _O()

        monkeypatch.setattr(mw_module, "REQUEST_COUNT", _FakeCounter())
        monkeypatch.setattr(mw_module, "REQUEST_LATENCY", _FakeHistogram())

        a = FastAPI()
        a.add_middleware(mw_module.PryHttpMiddleware)
        client = TestClient(a, client=("127.0.0.1", 5000))
        client.get(f"/scanner-noise-{id(object())}")

        assert recorded == ["unmatched"]
