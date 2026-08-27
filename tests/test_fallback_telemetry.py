"""Tests for the fallback telemetry recorder + diagnostics router.

Synthetic fallback journeys only — no live scraping. JSONL persistence is
disabled by default in this file so tests never touch the real data dir.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pry.api.routers.core.diagnostics import router as diagnostics_router
from pry.engine import fallback_telemetry


def _attempt(
    tier: str, success: bool, error: str | None = None, duration_ms: float = 100.0
) -> dict[str, Any]:
    return {"tier": tier, "success": success, "error": error, "duration_ms": duration_ms}


def _successful_journey(domain: str = "example.com") -> dict[str, Any]:
    return {
        "domain": domain,
        "tier_order": ["direct", "tls_fingerprint", "cloudscraper"],
        "attempts": [
            _attempt("direct", False, "timeout", 500.0),
            _attempt("tls_fingerprint", False, "timeout", 300.0),
            _attempt("cloudscraper", True, None, 900.0),
        ],
        "final_tier": "cloudscraper",
        "success": True,
        "duration_ms": 1700.0,
        "error": None,
    }


@pytest.fixture(autouse=True)
def _clean_telemetry() -> Any:
    """Hermetic state per test: empty ring, no real JSONL writes."""
    fallback_telemetry.reset()
    fallback_telemetry.set_jsonl_path(None)
    fallback_telemetry.set_jsonl_enabled(False)
    yield
    fallback_telemetry.reset()
    fallback_telemetry.set_jsonl_path(None)
    fallback_telemetry.set_jsonl_enabled(True)


class TestRecordAndDomainStats:
    """record_fallback + get_domain_stats correctness."""

    def test_domain_stats_for_successful_journey(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())

        stats = fallback_telemetry.get_domain_stats("example.com")
        assert stats["records"] == 1
        assert stats["successes"] == 1
        assert stats["failures"] == 0
        assert stats["success_rate"] == 1.0
        assert stats["avg_duration_ms"] == 1700.0

        # Per-tier: direct + tls_fingerprint failed (timeout), cloudscraper won.
        assert stats["tier_stats"]["direct"]["attempts"] == 1
        assert stats["tier_stats"]["direct"]["success_rate"] == 0.0
        assert stats["tier_stats"]["cloudscraper"]["success_rate"] == 1.0
        assert stats["tier_stats"]["cloudscraper"]["avg_duration_ms"] == 900.0

        assert stats["most_common_failure_reason"] == {"reason": "timeout", "count": 2}
        assert stats["winning_tiers"] == {"cloudscraper": 1}

    def test_domain_stats_for_failed_journey(self) -> None:
        fallback_telemetry.record_fallback(
            domain="blocked.example",
            tier_order=["direct", "tor"],
            attempts=[
                _attempt("direct", False, "403", 50.0),
                _attempt("tor", False, "blocked", 1200.0),
            ],
            final_tier=None,
            success=False,
            duration_ms=1250.0,
            error="all tiers failed",
        )

        stats = fallback_telemetry.get_domain_stats("blocked.example")
        assert stats["records"] == 1
        assert stats["successes"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["most_common_failure_reason"] == {"reason": "403", "count": 1}
        assert stats["winning_tiers"] == {}

    def test_unknown_domain_returns_empty_stats(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())

        stats = fallback_telemetry.get_domain_stats("other.example")
        assert stats["records"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["tier_stats"] == {}
        assert stats["most_common_failure_reason"] is None

    def test_domain_stats_are_scoped_per_domain(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey(domain="a.example"))
        fallback_telemetry.record_fallback(**_successful_journey(domain="b.example"))

        assert fallback_telemetry.get_domain_stats("a.example")["records"] == 1
        assert fallback_telemetry.get_domain_stats("b.example")["records"] == 1


class TestGlobalStats:
    """get_global_stats aggregation."""

    def test_global_stats_aggregate_success_and_failure(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())
        fallback_telemetry.record_fallback(
            domain="blocked.example",
            tier_order=["direct", "tor"],
            attempts=[
                _attempt("direct", False, "blocked", 50.0),
                _attempt("tor", False, "blocked", 1200.0),
                _attempt("google_cache", False, "blocked", 400.0),
            ],
            final_tier=None,
            success=False,
            duration_ms=1650.0,
            error="all tiers failed",
        )

        stats = fallback_telemetry.get_global_stats()
        assert stats["records"] == 2
        assert stats["domains"] == 2
        assert stats["successes"] == 1
        assert stats["failures"] == 1
        assert stats["overall_success_rate"] == 0.5
        assert stats["avg_tiers_per_success"] == 3.0
        assert stats["top_winning_tiers"] == [{"tier": "cloudscraper", "wins": 1}]
        # The successful journey also left 2 "timeout" failures behind.
        assert stats["top_failure_reasons"] == [
            {"reason": "blocked", "count": 3},
            {"reason": "timeout", "count": 2},
        ]

    def test_global_stats_empty(self) -> None:
        stats = fallback_telemetry.get_global_stats()
        assert stats["records"] == 0
        assert stats["overall_success_rate"] == 0.0
        assert stats["avg_tiers_per_success"] == 0.0
        assert stats["top_winning_tiers"] == []
        assert stats["top_failure_reasons"] == []


class TestRingBufferBounding:
    """Memory stays bounded: only the last N records are retained."""

    def test_ring_buffer_evicts_oldest(self) -> None:
        capacity = fallback_telemetry.DEFAULT_RING_SIZE
        overflow = capacity + 100
        for i in range(overflow):
            fallback_telemetry.record_fallback(
                domain=f"d{i}.example",
                tier_order=["direct"],
                attempts=[_attempt("direct", True, None, 10.0)],
                final_tier="direct",
                success=True,
                duration_ms=10.0,
                error=None,
            )

        stats = fallback_telemetry.get_global_stats()
        assert stats["records"] == capacity
        # Oldest records were evicted; the first domain is gone.
        assert "d0.example" not in fallback_telemetry.snapshot()["domain_summary"]
        assert f"d{capacity}.example" in fallback_telemetry.snapshot()["domain_summary"]

    def test_snapshot_reports_ring_usage(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())

        snap = fallback_telemetry.snapshot()
        assert snap["ring"]["capacity"] == fallback_telemetry.DEFAULT_RING_SIZE
        assert snap["ring"]["retained"] == 1


class TestSnapshotShape:
    """snapshot() is the diagnostics endpoint payload."""

    def test_snapshot_keys_and_recent_records(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())

        snap = fallback_telemetry.snapshot()
        assert snap["enabled"] is False  # JSONL disabled by the test fixture
        assert set(snap) == {
            "enabled",
            "jsonl_path_override",
            "ring",
            "global",
            "domain_summary",
            "recent_records",
        }

        assert snap["global"]["records"] == 1
        assert snap["domain_summary"] == {
            "example.com": {"records": 1, "successes": 1, "success_rate": 1.0}
        }

        assert isinstance(snap["recent_records"], list)
        assert len(snap["recent_records"]) == 1
        record = snap["recent_records"][0]
        assert set(record) == {
            "domain",
            "tier_order",
            "attempts",
            "final_tier",
            "success",
            "duration_ms",
            "error",
            "timestamp",
        }
        assert record["final_tier"] == "cloudscraper"
        assert record["success"] is True

    def test_snapshot_recent_limit_caps_payload(self) -> None:
        for i in range(10):
            journey = _successful_journey(domain=f"d{i}.example")
            fallback_telemetry.record_fallback(**journey)

        assert len(fallback_telemetry.snapshot(recent_limit=3)["recent_records"]) == 3
        assert len(fallback_telemetry.snapshot(recent_limit=0)["recent_records"]) == 0


class TestJsonlPersistence:
    """JSONL writes are best-effort and never fatal."""

    def test_writes_json_line_when_enabled(self, tmp_path: Any) -> None:
        path = tmp_path / "fallback.jsonl"
        fallback_telemetry.set_jsonl_path(path)
        fallback_telemetry.set_jsonl_enabled(True)

        fallback_telemetry.record_fallback(**_successful_journey())

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["domain"] == "example.com"
        assert payload["final_tier"] == "cloudscraper"
        assert payload["success"] is True
        assert payload["attempts"][0] == _attempt("direct", False, "timeout", 500.0)

    def test_write_failure_is_non_fatal(self, tmp_path: Any) -> None:
        # Point the log at a directory: opening it for append must fail
        # silently and must not raise out of record_fallback.
        fallback_telemetry.set_jsonl_path(tmp_path)
        fallback_telemetry.set_jsonl_enabled(True)

        fallback_telemetry.record_fallback(**_successful_journey())

        stats = fallback_telemetry.get_global_stats()
        assert stats["records"] == 1


class TestReset:
    """reset() clears retained state."""

    def test_reset_clears_records(self) -> None:
        fallback_telemetry.record_fallback(**_successful_journey())
        assert fallback_telemetry.get_global_stats()["records"] == 1

        fallback_telemetry.reset()

        assert fallback_telemetry.get_global_stats()["records"] == 0
        assert fallback_telemetry.snapshot()["recent_records"] == []


class TestDiagnosticsRouter:
    """The router is import-safe and exposes the snapshot."""

    def test_router_exposes_diagnostics_route(self) -> None:
        paths = {
            getattr(route, "path", None): getattr(route, "methods", None)
            for route in diagnostics_router.routes
        }
        assert "/v1/diagnostics" in paths
        assert paths["/v1/diagnostics"] == {"GET"}

    def test_router_module_imports_cleanly(self) -> None:
        # Importing the router must not raise (guards api.py wiring).
        import pry.api.routers.core.diagnostics  # noqa: F401
