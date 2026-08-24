# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""AbuseGuard tests: sabotage circuit breaker, throttle, honeypot telemetry."""

from __future__ import annotations

import asyncio
from typing import Any

from actor_factory.abuse_guard import AbuseGuard
from actor_factory.runner import ActorRunConfig, PPEScraperRunner


class TestCircuitBreaker:
    def test_trips_after_consecutive_failures(self) -> None:
        g = AbuseGuard(consecutive_limit=12)
        for _ in range(11):
            g.record("error", "http://x")
        assert not g.tripped
        g.record("error", "http://x")
        assert g.tripped
        assert "consecutive_failures=12" in g.trip_reason

    def test_success_resets_streak(self) -> None:
        g = AbuseGuard(consecutive_limit=12)
        for _ in range(11):
            g.record("error", "http://x")
        g.record("ok", "http://x")
        assert g.consecutive_failures == 0
        assert not g.tripped

    def test_rate_tripwire_fires_on_ninety_percent(self) -> None:
        g = AbuseGuard(rate_sample=15, rate_threshold=0.9, consecutive_limit=99)
        for n in range(15):
            g.record("error" if n < 14 else "ok", f"http://x/{n}")
        assert g.tripped
        assert "failure_rate=" in g.trip_reason

    def test_monitor_mode_ignores_skips(self) -> None:
        g = AbuseGuard(consecutive_limit=12, skip_counts_as_failure=False)
        for _ in range(20):
            g.record("skipped", "http://x")
        assert not g.tripped  # unchanged pages are normal for monitors
        g.record("error", "http://x")
        assert g.consecutive_failures == 1


class TestThrottle:
    def test_delay_zero_before_trip(self) -> None:
        g = AbuseGuard()
        g.record("ok", "http://x")
        assert g.delay == 0.0

    def test_escalates_and_caps(self) -> None:
        g = AbuseGuard(base_delay=0.5, max_delay=4.0)
        for _ in range(12):
            g.record("error", "http://x")
        assert g.delay == 0.5
        seen = [g.escalate_throttle() for _ in range(6)]
        assert seen[0] == 1.0
        assert seen[-1] == 4.0  # doubles then caps


class TestGraceAndAbort:
    def test_abort_only_after_grace_window_expires(self) -> None:
        g = AbuseGuard(consecutive_limit=3, grace_window=2)
        for _ in range(3):
            g.record("error", "http://x")
        assert g.tripped
        assert not g.should_abort
        g.record("error", "http://x")  # grace 2 -> 1
        assert not g.should_abort
        g.record("error", "http://x")  # grace 1 -> 0
        assert g.should_abort

    def test_recovery_inside_grace_standdown(self) -> None:
        g = AbuseGuard(consecutive_limit=3, grace_window=2)
        for _ in range(3):
            g.record("error", "http://x")
        g.record("ok", "http://x")
        assert not g.should_abort
        assert g.delay == 0.0


class TestHoneypotRecord:
    def test_carries_fingerprint_fields(self) -> None:
        g = AbuseGuard(consecutive_limit=2)
        g.record("error", "http://secret-target.example/a")
        g.record("error", "http://secret-target.example/b")
        rec = g.honeypot_record()
        assert rec["honeypot"] is True
        assert rec["status"] == "rejected"
        assert rec["stats"]["consecutive_failures"] == 2
        assert len(rec["url_hashes"]) == 2
        # URLs themselves are never leaked into the telemetry - hashes only
        assert all("secret-target" not in h for h in rec["url_hashes"])


class TestRunnerIntegration:
    @staticmethod
    async def _run_with(fail_first: int, total: int) -> tuple[Any, list[dict]]:
        pushed: list[dict] = []

        class FakeCharge:
            event_charge_limit_reached = False

        class FakeActor:
            async def __aenter__(self) -> FakeActor:
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            def on(self, *_a: Any, **_k: Any) -> None:
                return None

            async def get_input(self) -> dict:
                return {"urls": [f"http://t/{i}" for i in range(total)]}

            async def push_data(self, item: dict, event: str | None = None) -> FakeCharge:
                pushed.append(item)
                return FakeCharge()

        calls = {"n": 0}

        class Runner(PPEScraperRunner):
            async def process_url(self, url: str, options: dict[str, Any]) -> dict:
                n = calls["n"]
                calls["n"] += 1
                if n < fail_first:
                    return {"status": "error", "error": "boom", "method": "direct"}
                return {"status": "ok", "content": "fine", "method": "direct"}

        cfg = ActorRunConfig(primary_event="test-event", default_output_format="markdown")
        runner = Runner(config=cfg, actor_module=None)
        runner.actor = lambda: FakeActor()  # type: ignore[method-assign]
        await runner.run()
        return runner.stats, pushed

    def test_sabotage_input_aborts_early_with_honeypot(self) -> None:
        _stats, pushed = asyncio.run(self._run_with(fail_first=999, total=60))
        honeypots = [p for p in pushed if p.get("honeypot")]
        assert len(honeypots) == 1
        assert honeypots[0]["status"] == "rejected"
        # far fewer items processed than the 60 submitted
        assert len(pushed) < 30

    def test_transient_outage_recovers_and_completes(self) -> None:
        _stats, pushed = asyncio.run(self._run_with(fail_first=5, total=10))
        assert not any(p.get("honeypot") for p in pushed)
        assert sum(1 for p in pushed if p.get("status") == "ok") == 5
