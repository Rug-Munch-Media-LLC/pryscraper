# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Cost tracking coverage across the tracker and the registry."""

from __future__ import annotations

from pry.intelligence.llm.base import LLMCostTracker, LLMResponse, cost_tracker
from pry.intelligence.llm.registry import LLMRegistry
from tests.test_llm_providers.conftest import FakeProvider


def test_cost_tracker_records_and_resets() -> None:
    tracker = LLMCostTracker()
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p1", input_tokens=10, output_tokens=5, cost_usd=0.001
        )
    )
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p1", input_tokens=2, output_tokens=1, cost_usd=0.0001
        )
    )
    tracker.record(
        LLMResponse(
            text="", model="m", provider="p2", input_tokens=7, output_tokens=3, cost_usd=0.0005
        )
    )
    stats = tracker.stats()
    assert stats["calls"] == 3
    assert stats["input_tokens"] == 19
    assert stats["output_tokens"] == 9
    assert stats["per_provider"]["p1"]["calls"] == 2
    tracker.reset()
    assert tracker.stats()["calls"] == 0


async def test_registry_tracks_cost_via_cost_tracker() -> None:
    reg = LLMRegistry()
    provider = FakeProvider(
        name="costprov",
        outcomes=[
            LLMResponse(
                text="ok", model="m", provider="costprov", input_tokens=1000, output_tokens=500
            )
        ],
        cost_in=0.001,
        cost_out=0.002,
    )
    reg.register(provider)
    await reg.complete("hi", fallback=False)
    stats = cost_tracker.stats()
    assert stats["per_provider"]["costprov"]["calls"] == 1
    assert abs(stats["per_provider"]["costprov"]["cost_usd"] - 0.002) < 1e-9
