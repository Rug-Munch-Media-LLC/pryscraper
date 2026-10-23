"""Domain-scoped tier health + honest win/loss recording.

The production incident: ``tier_health.json`` was keyed by tier name alone.
Ten tiers sat at attempts=3, wins=0 — several with ``cost_ms_total=0`` (never
executed) — and the 15-tier ladder collapsed to 4 on EVERY domain. These tests
pin the three properties that prevent a repeat:

* a zero-win record on domain A never skips tier X on domain B;
* a record with no executed sample (``cost_ms_total == 0``) is not evidence;
* the chain records the post-block-detection success predicate, and a tier
  that could not run because its dependency was missing is not a loss.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

import pry.engine.scraper_orchestrate as so
from pry.engine import tier_health
from pry.engine.domain_key import memory_domain
from pry.engine.scraper_orchestrate import ScrapeOrchestrator

_URL = "https://blocked.example/page"


def _seed(path: Any, payload: dict[str, Any]) -> None:
    payload.setdefault("_policy", tier_health.POLICY_VERSION)
    path.write_text(json.dumps(payload))


def test_a_zero_win_tier_on_domain_a_does_not_skip_domain_b(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    for _ in range(tier_health.MIN_EVIDENCE_ATTEMPTS):
        tier_health.record("camoufox", won=False, cost_ms=30_000, path=path, domain="a.example")
    assert tier_health.should_skip("camoufox", path=path, domain="a.example")[0] is True
    assert tier_health.should_skip("camoufox", path=path, domain="b.example") == (
        False,
        "no_evidence",
    )
    # The write is domain-scoped; no unscoped key exists to poison other sites.
    raw = json.loads(path.read_text())
    assert "a.example|camoufox" in raw
    assert "camoufox" not in raw


def test_a_tier_with_zero_executed_samples_is_never_skipped(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    _seed(
        path,
        {"a.example|direct": {"attempts": 5, "wins": 0, "losses": 5, "cost_ms_total": 0}},
    )
    assert tier_health.should_skip("direct", path=path, domain="a.example") == (
        False,
        "no_executed_samples",
    )


def test_stale_evidence_expires(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    old = time.time() - tier_health.STALE_AFTER_S - 60
    _seed(
        path,
        {
            "a.example|direct": {
                "attempts": 9,
                "wins": 0,
                "losses": 9,
                "cost_ms_total": 9_000,
                "last_seen": old,
            }
        },
    )
    assert tier_health.should_skip("direct", path=path, domain="a.example") == (
        False,
        "stale_evidence",
    )


def test_legacy_global_keys_are_dropped_on_the_next_domain_write(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    _seed(path, {"camoufox": {"attempts": 9, "wins": 0, "losses": 9, "cost_ms_total": 1_000}})
    tier_health.record("direct", won=True, cost_ms=5, path=path, domain="a.example")
    raw = json.loads(path.read_text())
    assert "camoufox" not in raw
    assert "a.example|direct" in raw


def test_an_unavailable_tier_is_not_recorded_as_a_loss(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    tier_health.record(
        "tor", won=False, cost_ms=1_000, path=path, domain="a.example", unavailable=True
    )
    assert not path.exists()


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

    async def _attempt_tier(
        self, tier_name: str, tier_fn: Any, url: str, proxy_url: str | None, opts: dict[str, Any]
    ) -> tuple[Any, float, bool]:
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


def test_circuit_breaker_open_state_survives_store_reload(tmp_path: Any) -> None:
    """Breaker open/half-open state persists with the same TTL as tier health.

    ``last_failure_at`` + ``recovery_seconds`` are serialized together, so a
    restart does not resurrect a tripped service: the remaining cooldown is
    identical to the one the previous process would have enforced.
    """
    from pry.engine.resilience import ResilienceRegistry
    from pry.engine.resilience_circuit import CircuitState

    path = tmp_path / "resilience_state.json"
    before = ResilienceRegistry(persist_path=path, method_stats=False)
    cb = before.breaker("openrouter")
    cb.state = CircuitState.OPEN
    cb.failures = 7
    cb.last_failure_at = time.time()
    cb.recovery_seconds = 120.0
    assert before.save() is True

    after = ResilienceRegistry(persist_path=path, method_stats=False)
    restored = after.breaker("openrouter")
    assert restored.state == CircuitState.OPEN
    assert restored.failures == 7
    assert restored.recovery_seconds == 120.0
    # TTL is still in force: the cooldown did not reset on reload.
    assert restored.is_allowed() is False


def test_circuit_breaker_half_open_state_survives_reload(tmp_path: Any) -> None:
    from pry.engine.resilience import ResilienceRegistry
    from pry.engine.resilience_circuit import CircuitState

    path = tmp_path / "resilience_state.json"
    before = ResilienceRegistry(persist_path=path, method_stats=False)
    cb = before.breaker("ollama")
    cb.state = CircuitState.HALF_OPEN
    cb.half_open_attempts = 1
    assert before.save() is True

    restored = ResilienceRegistry(persist_path=path, method_stats=False).breaker("ollama")
    assert restored.state == CircuitState.HALF_OPEN
    assert restored.half_open_attempts == 1
