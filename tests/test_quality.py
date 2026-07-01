"""Tests for data quality SLA dashboard."""

from quality import (
    compute_completeness,
    compute_freshness,
    compute_null_rate,
    detect_anomalies,
)


def test_compute_completeness_full() -> None:
    data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
    result = compute_completeness(data)
    assert result["score"] == 100.0
    assert result["filled_fields"] == 3


def test_compute_completeness_partial() -> None:
    data = {"name": "Alice", "age": None, "email": ""}
    result = compute_completeness(data)
    assert result["score"] < 100


def test_compute_completeness_empty() -> None:
    result = compute_completeness({})
    assert result["score"] == 0


def test_compute_completeness_list() -> None:
    data = [{"a": 1, "b": 2}, {"a": 3, "b": None}, {"a": 5, "b": 6}]
    result = compute_completeness(data)
    assert result["record_count"] == 3
    assert result["score"] > 0


def test_compute_freshness_fresh() -> None:
    import time

    data = {"timestamp": time.time()}
    result = compute_freshness(data, max_age_seconds=3600)
    assert result["fresh"] is True


def test_compute_freshness_stale() -> None:
    data = {"timestamp": 1000000}  # Old timestamp
    result = compute_freshness(data, max_age_seconds=3600)
    assert result["fresh"] is False


def test_compute_null_rate() -> None:
    data = {"a": 1, "b": None, "c": "", "d": 4}
    result = compute_null_rate(data)
    assert result["b"]["null_rate"] == 100.0
    assert result["c"]["empty_rate"] == 100.0
    assert result["a"]["null_rate"] == 0.0


def test_detect_anomalies_empty_result() -> None:
    anomalies = detect_anomalies({}, {"key": "value"})
    assert len(anomalies) == 1
    assert anomalies[0]["type"] == "empty_result"


def test_detect_anomalies_missing_field() -> None:
    anomalies = detect_anomalies({"a": 1}, {"a": 1, "b": 2})
    assert any(a["type"] == "missing_field" for a in anomalies)


def test_detect_anomalies_value_swing() -> None:
    anomalies = detect_anomalies({"price": 200}, {"price": 10})
    assert any(a["type"] == "value_swing" for a in anomalies)


def test_detect_anomalies_no_previous() -> None:
    anomalies = detect_anomalies({"a": 1}, None)
    assert len(anomalies) == 0
