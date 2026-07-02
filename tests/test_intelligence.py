# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for competitive intelligence engine."""

from intelligence import (
    compute_field_statistics,
    generate_alert,
    generate_weekly_report,
    get_snapshots,
    record_snapshot,
)


def test_record_snapshot() -> None:
    result = record_snapshot(
        "comp_1", "Competitor A", "https://example.com", {"price": 99.99, "stock": "in_stock"}
    )
    assert "ts" in result
    assert result["competitor_name"] == "Competitor A"


def test_get_snapshots() -> None:
    record_snapshot("comp_test", "Test", "https://example.com", {"a": 1})
    snapshots = get_snapshots("comp_test")
    assert len(snapshots) >= 1
    assert snapshots[0]["competitor_name"] == "Test"


def test_compute_field_statistics_numeric() -> None:
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


def test_generate_alert_price_change() -> None:
    alert = generate_alert("Competitor A", "price", 100, 120)
    assert "Competitor A" in alert
    assert "increased" in alert or "changed" in alert


def test_generate_alert_decrease() -> None:
    alert = generate_alert("Competitor B", "price", 200, 150)
    assert "decreased" in alert


def test_generate_alert_text_change() -> None:
    alert = generate_alert("Competitor C", "description", "Old desc", "New and improved")
    assert "Competitor C" in alert


def test_generate_report() -> None:
    record_snapshot("comp_rpt", "Report Co", "https://example.com", {"price": 50})
    report = generate_weekly_report([{"id": "comp_rpt", "name": "Report Co"}], days_back=7)
    assert "report_period" in report
    assert "generated_at" in report
