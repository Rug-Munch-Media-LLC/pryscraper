# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared doubles and hermetic fixtures for the LLM provider tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from pry.intelligence.llm.base import LLMProvider, LLMResponse, cost_tracker


class FakeProvider(LLMProvider):
    """Configurable fake provider: scripted outcomes or default success."""

    name = "fake"

    def __init__(
        self,
        name: str = "fake",
        outcomes: list[LLMResponse | Exception] | None = None,
        cost_in: float = 0.0,
        cost_out: float = 0.0,
    ) -> None:
        self.name = name
        self.outcomes = list(outcomes or [])
        self.calls = 0
        self.cost_per_1k_input = cost_in
        self.cost_per_1k_output = cost_out

    async def complete(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return LLMResponse(text="ok", model="fake", provider=self.name)

    async def embed(self, *args, **kwargs) -> list[float]:
        return []

    async def stream_chat(self, *args, **kwargs):
        response = await self.complete(*args, **kwargs)
        yield response.text


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"status {status}", request=request, response=response)


@pytest.fixture(autouse=True)
def _llm_hermetic(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate usage persistence + referral writes; reset the cost tracker."""
    monkeypatch.setattr("pry.intelligence.llm.registry.USAGE_DIR", tmp_path)
    monkeypatch.setattr("pry.commerce.referrals.ReferralTracker", MagicMock)
    cost_tracker.reset()
    yield
    cost_tracker.reset()
