# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for competitive intelligence engine."""

import time
from collections.abc import Iterator

import pytest

from pry.api.intelligence import (
    compute_field_statistics,
    detect_anomalies_numeric,
    generate_alert,
    generate_weekly_report,
    get_snapshots,
    record_snapshot,
)
from pry.core.db import Base, get_engine


@pytest.fixture(autouse=True)
def _intel_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use in-memory SQLite for each test."""
    monkeypatch.setenv("PRY_DATABASE_URL", "sqlite://")
    import pry.core.db as db_module

    db_module._engine = None
    db_module._SessionLocal = None
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


# -- Snapshot recording --


def test_record_snapshot() -> None:
    result = record_snapshot(
        "comp_1",
        "Competitor A",
        "https://example.com",
        {"price": 99.99, "stock": "in_stock"},
    )
    assert "ts" in result
    assert "unix_ts" in result
    assert result["competitor_name"] == "Competitor A"
    assert result["competitor_id"] == "comp_1"
    assert result["fields"]["price"] == 99.99


def test_record_snapshot_returns_iso_ts() -> None:
    result = record_snapshot("comp_ts", "TS Co", "https://example.com", {"x": 1})
    ts = result["ts"]
    assert isinstance(ts, str)
    assert ts.endswith("Z") or "+" in ts


def test_record_snapshot_unix_ts() -> None:
    before = time.time()
    result = record_snapshot("comp_ut", "UT Co", "https://example.com", {"x": 1})
    after = time.time()
    assert before <= result["unix_ts"] <= after + 1


# -- Retreiving snapshots --


def test_get_snapshots() -> None:
    record_snapshot("comp_test", "Test", "https://example.com", {"a": 1})
    snapshots = get_snapshots("comp_test")
    assert len(snapshots) >= 1
    assert snapshots[0]["competitor_name"] == "Test"
    assert snapshots[0]["fields"]["a"] == 1


def test_get_snapshots_limit() -> None:
    for i in range(10):
        record_snapshot("comp_limit", "Limit Co", "https://example.com", {"i": i})
    snapshots = get_snapshots("comp_limit", limit=3)
    assert len(snapshots) == 3


def test_get_snapshots_ordered_by_ts_desc() -> None:
    for i in range(5):
        record_snapshot("comp_order", "Order Co", "https://example.com", {"i": i})
        time.sleep(0.01)
    snapshots = get_snapshots("comp_order")
    assert len(snapshots) == 5
    assert snapshots[0]["fields"]["i"] == 4


def test_get_snapshots_since_hours() -> None:
    record_snapshot("comp_since", "Since Co", "https://example.com", {"val": 1})
    snapshots = get_snapshots("comp_since", since_hours=1)
    assert len(snapshots) >= 1


def test_get_snapshots_empty_for_unknown() -> None:
    snapshots = get_snapshots("nonexistent_comp")
    assert snapshots == []


# -- Field statistics --


class TestComputeFieldStatistics:
    def test_numeric(self) -> None:
        snapshots = [
            {"fields": {"price": 100}},
            {"fields": {"price": 110}},
            {"fields": {"price": 105}},
        ]
        stats = compute_field_statistics(snapshots, "price")
        assert stats["has_history"] is True
        assert stats["mean"] == 105.0
        assert stats["min"] == 100
        assert stats["max"] == 110

    def test_insufficient_data(self) -> None:
        snapshots = [{"fields": {"price": 100}}]
        stats = compute_field_statistics(snapshots, "price")
        assert stats["has_history"] is False

    def test_empty_snapshots(self) -> None:
        stats = compute_field_statistics([], "price")
        assert stats["count"] == 0
        assert stats["has_history"] is False

    def test_missing_field(self) -> None:
        snapshots = [{"fields": {"price": 100}}, {"fields": {"other": 200}}]
        stats = compute_field_statistics(snapshots, "price")
        assert stats["count"] == 1
        assert stats["has_history"] is False

    def test_string_field(self) -> None:
        snapshots = [
            {"fields": {"status": "active"}},
            {"fields": {"status": "active"}},
            {"fields": {"status": "paused"}},
        ]
        stats = compute_field_statistics(snapshots, "status")
        assert stats["has_history"] is True
        assert stats["unique_values"] == 2
        assert stats["latest"] == "paused"


# -- Anomaly detection --


class TestDetectAnomaliesNumeric:
    def test_detects_anomaly(self) -> None:
        history = [100.0, 102.0, 101.0, 103.0, 99.0, 101.0, 102.0]
        result = detect_anomalies_numeric(150.0, history)
        assert result["anomaly"] is True
        assert result["z_score"] >= 2.0

    def test_insufficient_history(self) -> None:
        result = detect_anomalies_numeric(100.0, [])
        assert result["anomaly"] is False
        assert "Insufficient history" in result["reason"]

    def test_no_anomaly(self) -> None:
        history = [100.0, 101.0, 100.0, 101.0, 100.0]
        result = detect_anomalies_numeric(100.0, history)
        assert result["anomaly"] is False

    def test_constant_history_same_value(self) -> None:
        history = [100.0, 100.0, 100.0]
        result = detect_anomalies_numeric(100.0, history)
        assert result["anomaly"] is False

    def test_constant_history_diff_value(self) -> None:
        history = [100.0, 100.0, 100.0]
        result = detect_anomalies_numeric(200.0, history)
        assert result["anomaly"] is True
        assert "constant history" in result["reason"]


# -- Alerts --


class TestGenerateAlert:
    def test_price_increase(self) -> None:
        alert = generate_alert("Competitor A", "price", 100, 120)
        assert "Competitor A" in alert
        assert "increased" in alert

    def test_price_decrease(self) -> None:
        alert = generate_alert("Competitor B", "price", 200, 150)
        assert "decreased" in alert

    def test_text_change_short(self) -> None:
        alert = generate_alert("Competitor C", "description", "Old desc", "New and improved")
        assert "Competitor C" in alert
        assert '"Old desc"' in alert

    def test_text_change_long(self) -> None:
        long_old = "x" * 60
        long_new = "y" * 60
        alert = generate_alert("Competitor D", "description", long_old, long_new)
        assert "chars" in alert

    def test_with_anomaly_info(self) -> None:
        alert = generate_alert(
            "Competitor F",
            "price",
            100,
            200,
            anomaly_info={"anomaly": True, "z_score": 3.5, "pct_change": 100.0},
        )
        assert "ANOMALY DETECTED" in alert
        assert "z-score" in alert


# -- Weekly report --


class TestGenerateWeeklyReport:
    def test_basic_report(self) -> None:
        record_snapshot("comp_rpt", "Report Co", "https://example.com", {"price": 50})
        report = generate_weekly_report([{"id": "comp_rpt", "name": "Report Co"}], days_back=7)
        assert "report_period" in report
        assert "generated_at" in report
        assert report["competitors_tracked"] == 1

    def test_report_with_changes(self) -> None:
        record_snapshot("comp_chg", "Chg Co", "https://example.com", {"price": 100})
        record_snapshot("comp_chg", "Chg Co", "https://example.com", {"price": 150})
        report = generate_weekly_report([{"id": "comp_chg", "name": "Chg Co"}], days_back=7)
        assert report["total_changes"] >= 1
        assert report["most_active_competitor"] == "Chg Co"

    def test_report_no_activity(self) -> None:
        report = generate_weekly_report(
            [{"id": "comp_inactive", "name": "Inactive Co"}],
            days_back=7,
        )
        assert report["total_changes"] == 0

    def test_report_multiple_competitors(self) -> None:
        record_snapshot("comp_a", "Alpha Co", "https://example.com", {"price": 50})
        record_snapshot("comp_b", "Beta Co", "https://example.com", {"price": 75})
        competitors = [
            {"id": "comp_a", "name": "Alpha Co"},
            {"id": "comp_b", "name": "Beta Co"},
        ]
        report = generate_weekly_report(competitors, days_back=7)
        assert report["competitors_tracked"] == 2
