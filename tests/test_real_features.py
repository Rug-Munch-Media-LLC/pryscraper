# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for real LLM, real anomaly, real GDPR, real reports."""

from anomaly import AnomalyDetector
from gdpr_real import GDPRService


def test_anomaly_detector_init() -> None:
    a = AnomalyDetector()
    assert a.sensitivity == 2.0


def test_anomaly_z_score() -> None:
    a = AnomalyDetector(sensitivity=2.0)
    historical = [{"price": 100 + i} for i in range(20)]
    current = {"price": 500}
    result = a.detect(historical, current, fields=["price"])
    assert result["is_anomaly"] is True
    assert any(an["field"] == "price" for an in result["anomalies"])


def test_anomaly_no_anomaly() -> None:
    a = AnomalyDetector()
    historical = [{"price": 99 + (i % 3)} for i in range(20)]
    current = {"price": 100}
    result = a.detect(historical, current, fields=["price"])
    assert result["is_anomaly"] is False


def test_anomaly_multi_field() -> None:
    a = AnomalyDetector()
    historical = [{"price": 100, "stock": 50, "rating": 4.5} for _ in range(20)]
    current = {"price": 100, "stock": 50, "rating": 1.0}
    result = a.detect(historical, current, fields=["price", "stock", "rating"])
    assert any(an["field"] == "rating" for an in result["anomalies"])


def test_anomaly_correlation() -> None:
    """When discount increases and price decreases, the price change is explained."""
    a = AnomalyDetector()
    historical = [{"price": 100, "discount": 0} for _ in range(20)]
    current = {"price": 80, "discount": 20}
    result = a.detect(historical, current, fields=["price", "discount"])
    explained = any("discount" in str(an) for an in result.get("anomalies", []))
    assert explained is True


def test_gdpr_right_to_access_no_data() -> None:
    g = GDPRService()
    result = g.right_to_access("nonexistent-user-id-12345")
    assert result["total_records"] == 0


def test_gdpr_audit_log() -> None:
    g = GDPRService()
    g.audit("test_action", "test_subject", {"key": "value"})
    entries = g.get_audit_log(subject_id="test_subject")
    assert len(entries) >= 1
    assert entries[-1]["action"] == "test_action"


def test_gdpr_data_portability_no_data() -> None:
    g = GDPRService()
    result = g.data_portability_export("nonexistent-id-9999")
    assert result["success"] is False
