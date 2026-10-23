"""What the orchestration chain records after block detection.

A block page is a LOSS for the tier that fetched it — recording the win on
HTTP 200 is how 339 of 1206 attempts went to tiers that had never won. A tier
whose dependency is missing never reached the network, so it is not a sample
at all and must not create an entry.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import pry.engine.scraper_orchestrate as so
from pry.engine.domain_key import memory_domain
from pry.engine.scraper_orchestrate import ScrapeOrchestrator

_URL = "https://blocked.example/page"


class _Signal:
    kind = "cloudflare"
    confidence = 0.9
    recommended_escalation = "browser"
    evidence = ("challenge-marker",)


class _Stub(ScrapeOrchestrator):
    """Drive the real fallback loop with one stubbed tier."""

    def __init__(self, html: str | None, tier: str = "direct") -> None:
        self.html = html
        self.tier = tier
        self._last_skipped_tiers: list[str] = []

    def _resolve_proxy_url(self, opts: dict[str, Any]) -> None:
        return None

    def _build_tier_order(
        self, proxy_url: str | None, premium_first: bool, domain: str | None = None
    ) -> list[tuple[str, Any]]:
        return [(self.tier, object())]

    async def _attempt_tier(self, *_args: Any, **_kw: Any) -> tuple[Any, float, bool]:
        return self.html, 0.5, False

    def _detect_block_signal(self, html: str | None) -> Any:
        return _Signal() if html else None

    def _is_valid(self, html: str | None) -> bool:
        return True

    def _promote_preferred_tiers(self, *_args: Any, **_kw: Any) -> None:
        return None

    def _record_tier_success(self, **_kw: Any) -> dict[str, Any]:
        return {"status": "ok"}

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
        return {"reachability": "blocked", "blame_tier": False}

    monkeypatch.setattr(so, "reachability_verdict", _verdict)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_quiet")
async def test_a_block_page_records_a_loss_not_a_win(
    pry_tier_health_isolation: Any,
) -> None:
    long_block = "<html><body>" + ("blocked by waf " * 200) + "</body></html>"
    result = await _Stub(long_block)._scrape_with_fallbacks(_URL)
    assert result["status"] == "error"

    raw = json.loads(pry_tier_health_isolation.read_text())
    entry = raw[f"{memory_domain(_URL)}|direct"]
    assert entry["attempts"] == 1
    assert entry["wins"] == 0
    assert entry["losses"] == 1
    assert entry["cost_ms_total"] > 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("_quiet")
async def test_a_missing_dependency_does_not_count_as_a_loss(
    pry_tier_health_isolation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pry.engine import ultimate_scraper as us

    monkeypatch.setattr(us, "_has_tor", False)
    await _Stub(None, tier="tor")._scrape_with_fallbacks(_URL)
    assert not pry_tier_health_isolation.exists() or (
        f"{memory_domain(_URL)}|tor" not in json.loads(pry_tier_health_isolation.read_text())
    )
