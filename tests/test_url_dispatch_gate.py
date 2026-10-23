"""The dispatch seam: a terminal URL never touches a tier, and a win is a win.

Split from ``test_url_terminal_state`` so each module stays inside the 200-line
new-file cap: that file owns the state (cap, cooldown, pruning), this one owns
the wiring — gate before the semaphore, outcome recorded once per attempt.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

import pry.engine.scraper_orchestrate as so
from pry.engine import url_terminal_state
from pry.engine.scraper_orchestrate import ScrapeOrchestrator

_URL = "https://medium.com/blog/in-case-you-missed-it-june-2016-8505534e0ac9"


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    """Every test starts and ends with an empty table."""
    url_terminal_state.reset()
    yield
    url_terminal_state.reset()


class _Stub(ScrapeOrchestrator):
    """Real fallback loop, one zero-retry tier, mocks at the network seam."""

    def __init__(self) -> None:
        self.tier = AsyncMock(return_value=None)
        self.tier_orders: int = 0
        self._last_skipped_tiers: list[str] = []

    def _resolve_proxy_url(self, opts: dict[str, Any]) -> None:
        return None

    def _build_tier_order(
        self, proxy_url: str | None, premium_first: bool, domain: str | None = None
    ) -> list[tuple[str, Any]]:
        self.tier_orders += 1
        return [("undetected", self.tier)]

    def _detect_block_signal(self, html: str | None) -> None:
        return None

    def _record_telemetry(self, *_args: Any, **_kw: Any) -> None:
        return None

    def _recommend_proxy(self, last_error: str) -> None:
        return None


@pytest.fixture
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    from pry.engine import ultimate_scraper as us

    reg = us.registry
    monkeypatch.setattr(reg, "reorder_for_domain", lambda domain, names: list(names))
    monkeypatch.setattr(reg, "is_service_allowed", lambda name: True)
    monkeypatch.setattr(reg, "record_domain_tier_result", lambda *a, **k: None)
    monkeypatch.setattr(reg, "record_service_result", lambda *a, **k: None)
    monkeypatch.setattr(so, "validate_url", lambda url: url)

    async def _verdict(_url: str) -> dict[str, Any]:
        return {"reachability": "unknown", "blame_tier": False}

    monkeypatch.setattr(so, "reachability_verdict", _verdict)


class _WinningStub(_Stub):
    """A scraper whose ladder always wins."""

    async def _scrape_with_fallbacks(
        self, url: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"status": "ok", "url": url, "raw_html": "<html></html>", "method": "direct"}


class _RaisingStub(_Stub):
    """A scraper whose ladder raises instead of returning a failure."""

    async def _scrape_with_fallbacks(
        self, url: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("ladder exploded")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_quiet")
async def test_a_terminal_url_never_touches_a_tier(pry_tier_health_isolation: Any) -> None:
    stub = _Stub()
    for attempt in range(url_terminal_state.max_attempts()):
        result = await stub.scrape(_URL)
        assert result["verdict"] != "url_terminal", f"terminal too early at {attempt}"
        stub.tier.assert_called_once()
        stub.tier.reset_mock()

    orders_before = stub.tier_orders
    result = await stub.scrape(_URL)

    assert result["verdict"] == "url_terminal"
    assert result["status"] == "error"
    assert result["tiers_attempted"] == []
    stub.tier.assert_not_called()
    assert stub.tier_orders == orders_before  # stopped before tier selection


@pytest.mark.asyncio
@pytest.mark.usefixtures("_quiet")
async def test_repeated_wins_never_make_a_url_terminal() -> None:
    """Regression for the success-status bug on the real production path."""
    stub = _WinningStub()
    for _ in range(url_terminal_state.max_attempts() + 2):
        result = await stub.scrape(_URL)
        assert result["status"] == "ok"
    assert url_terminal_state.terminal_reason(_URL) is None
    assert stub.tier_orders == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("_quiet")
async def test_raised_attempts_count_and_then_short_circuit() -> None:
    stub = _RaisingStub()
    for _ in range(url_terminal_state.max_attempts()):
        with pytest.raises(RuntimeError):
            await stub.scrape(_URL)
    assert url_terminal_state.terminal_reason(_URL) is not None
    result = await stub.scrape(_URL)
    assert result["verdict"] == "url_terminal"
