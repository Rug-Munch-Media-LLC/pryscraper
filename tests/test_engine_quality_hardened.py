# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hardened tests for engine/quality.py — untested branches.

Complements tests/test_quality.py and tests/test_quality_mutation.py by
targeting the branches those suites do not reach:

* ``run_quality_check`` — the async aggregate (never exercised elsewhere).
* ``compute_completeness`` with an explicit ``schema`` argument.
* ``_compute_list_completeness`` with a list of non-dict records.
* ``compute_schema_adherence`` with a list input and a missing field.
* ``compute_null_rate`` with an empty dict.
* ``detect_anomalies`` with an empty *previous* dict and content-drift at
  the exact 0.5 ratio boundary.
* ``compute_freshness`` with ``max_age_seconds=0`` and negative ages.
* ``_format_age`` with negative seconds.
* ``run_quality_check`` error handling for a corrupt history file.

Every assertion pins a concrete value / type / outcome — no tautologies.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import pry.engine.quality as quality_module
import pry.engine.quality_checks.freshness as _fq
from pry.engine.quality import (
    compute_completeness,
    compute_freshness,
    compute_null_rate,
    compute_schema_adherence,
    detect_anomalies,
    run_quality_check,
)

# ── compute_completeness with explicit schema ───────────────────────────────


class TestCompletenessWithSchema:
    def test_schema_argument_is_accepted_and_ignored_for_dict(self) -> None:
        # The schema param is threaded through but does not change the
        # dict-completeness result (it only matters for list records).
        result = compute_completeness({"a": 1, "b": None}, schema={"a": "x"})
        assert result["score"] == 50.0
        assert result["total_fields"] == 2
        assert result["filled_fields"] == 1

    def test_list_with_schema_still_scores_records(self) -> None:
        result = compute_completeness([{"a": 1}], schema={"a": "x"})
        assert result["record_count"] == 1
        assert result["score"] == 100.0


# ── _compute_list_completeness edge cases ───────────────────────────────────


class TestListCompletenessEdgeCases:
    def test_list_of_only_non_dict_records(self) -> None:
        # No dict records -> no record_scores -> avg/min/max all 0, score 0.
        result = compute_completeness(["junk", 42, None])
        assert result["score"] == 0
        assert result["record_count"] == 3
        assert result["avg_record_score"] == 0
        assert result["min_record_score"] == 0
        assert result["max_record_score"] == 0

    def test_mixed_dict_and_non_dict_records(self) -> None:
        result = compute_completeness([{"a": 1, "b": 2}, "junk"])
        assert result["record_count"] == 2
        assert result["score"] == 100.0  # only the dict contributes
        assert result["min_record_score"] == 100.0
        assert result["max_record_score"] == 100.0


# ── compute_schema_adherence list + missing field ───────────────────────────


class TestSchemaAdherenceList:
    def test_list_input_aggregates_checks(self) -> None:
        result = compute_schema_adherence(
            [{"a": 1, "b": "x"}, {"a": "bad", "b": 2}], {"a": int, "b": str}
        )
        assert result["total_checks"] == 4
        assert result["type_mismatches"] == 2
        expected = {"a": 1, "b": 1}
        assert result["field_issues"] == expected
        assert result["score"] == 50.0

    def test_missing_field_is_not_counted_as_mismatch(self) -> None:
        # record.get(field) -> None for a missing key; None is exempt.
        result = compute_schema_adherence({"a": 1}, {"a": int, "b": str})
        assert result["total_checks"] == 2
        assert result["type_mismatches"] == 0
        assert result["score"] == 100.0

    def test_non_dict_records_are_skipped(self) -> None:
        result = compute_schema_adherence(["junk", {"a": 1}], {"a": int})
        assert result["total_checks"] == 1
        assert result["type_mismatches"] == 0
        assert result["score"] == 100.0


# ── compute_null_rate edge cases ────────────────────────────────────────────


class TestNullRateEdgeCases:
    def test_empty_dict_returns_empty_stats(self) -> None:
        assert compute_null_rate({}) == {}

    def test_empty_list_returns_empty_stats(self) -> None:
        assert compute_null_rate([]) == {}

    def test_non_dict_records_are_skipped(self) -> None:
        assert compute_null_rate(["junk", 42]) == {}


# ── detect_anomalies edge cases ─────────────────────────────────────────────


class TestDetectAnomaliesEdgeCases:
    def test_empty_previous_dict_flags_new_fields(self) -> None:
        # previous_data={} is falsy but not None, so the empty_result branch
        # does not fire; instead every current key is a "new_field".
        result = detect_anomalies({"a": 1}, {})
        expected = ["new_field"]
        assert [a["type"] for a in result] == expected
        assert result[0]["field"] == "a"
        assert result[0]["severity"] == "info"

    def test_both_empty_returns_empty_result(self) -> None:
        # current_data={} and previous_data={} -> previous is falsy, so the
        # `not current_data and previous_data` guard is False -> no anomaly.
        assert detect_anomalies({}, {}) == []

    def test_content_drift_at_exact_ratio_boundary(self) -> None:
        # ratio < 0.5 is required (strict). Build two long strings whose
        # SequenceMatcher ratio is EXACTLY 0.5 -> must NOT drift.
        # prev = "a"*20 + "b"*20, curr = "a"*20 + "c"*20:
        #   M (matching chars) = 20, ratio = 2*20 / (40+40) = 0.5.
        prev = "a" * 20 + "b" * 20
        curr = "a" * 20 + "c" * 20
        ratio = __import__("difflib").SequenceMatcher(None, prev, curr).ratio()
        assert ratio == 0.5
        result = detect_anomalies({"t": curr}, {"t": prev})
        assert [a for a in result if a["type"] == "content_drift"] == []

    def test_content_drift_just_below_ratio_boundary(self) -> None:
        # ratio slightly below 0.5 (e.g. 0.475) MUST drift.
        prev = "a" * 20 + "b" * 20
        curr = "a" * 19 + "c" * 21
        ratio = __import__("difflib").SequenceMatcher(None, prev, curr).ratio()
        assert ratio < 0.5
        result = detect_anomalies({"t": curr}, {"t": prev})
        drifts = [a for a in result if a["type"] == "content_drift"]
        assert len(drifts) == 1
        assert drifts[0]["severity"] == "medium"
        assert drifts[0]["similarity"] < 0.5

    def test_identical_long_text_does_not_drift(self) -> None:
        prev = "the same long sentence repeated over and over for content drift"
        result = detect_anomalies({"t": prev}, {"t": prev})
        assert [a for a in result if a["type"] == "content_drift"] == []

    def test_previous_data_none_returns_empty_list(self) -> None:
        assert detect_anomalies({"a": 1}, None) == []


# ── compute_freshness / _format_age edge cases ──────────────────────────────


class TestFreshnessEdgeCases:
    def test_max_age_zero_marks_any_age_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frozen = 1_800_000_000.0
        monkeypatch.setattr(_fq.time, "time", lambda: frozen)
        result = compute_freshness({"timestamp": frozen - 1}, max_age_seconds=0)
        assert result["fresh"] is False
        assert result["age_seconds"] == 1

    def test_negative_age_is_fresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A timestamp in the future yields a negative age; still fresh.
        frozen = 1_800_000_000.0
        monkeypatch.setattr(_fq.time, "time", lambda: frozen)
        result = compute_freshness({"timestamp": frozen + 100}, max_age_seconds=3600)
        assert result["fresh"] is True
        assert result["age_seconds"] == -100

    def test_float_timestamp_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frozen = 1_800_000_000.0
        monkeypatch.setattr(_fq.time, "time", lambda: frozen)
        result = compute_freshness({"timestamp": frozen - 0.5})
        # age = 0.5s; round(0.5) == 0 in Python 3 (banker's rounding).
        assert result["age_seconds"] == 0
        assert isinstance(result["age_seconds"], int)
        assert result["fresh"] is True

    def test_iso_timestamp_with_timezone_offset(self) -> None:
        # ISO string with explicit +00:00 offset parses fine.
        ts = datetime.now(UTC).replace(microsecond=0) - __import__("datetime").timedelta(seconds=5)
        result = compute_freshness({"scraped_at": ts.isoformat()})
        assert result["fresh"] is True
        assert isinstance(result["age_seconds"], int)


class TestFormatAgeNegative:
    def test_negative_seconds_formats_as_seconds(self) -> None:
        assert _fq._format_age(-5) == "-5s"


# ── run_quality_check (async aggregate) ─────────────────────────────────────


class TestRunQualityCheck:
    @pytest.fixture(autouse=True)
    def _isolate_quality_dir(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point QUALITY_DIR at a temp dir so history writes don't touch prod.
        monkeypatch.setattr(quality_module, "QUALITY_DIR", tmp_path)

    async def test_full_check_returns_contracted_shape(self) -> None:
        data = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        result = await run_quality_check("https://example.com", data)
        expected = {
            "url",
            "quality_score",
            "completeness",
            "schema_adherence",
            "freshness",
            "null_rates",
            "anomalies",
            "anomaly_count",
            "critical_anomalies",
            "has_previous_data",
            "checked_at",
        }
        assert set(result.keys()) == expected
        assert result["url"] == "https://example.com"
        assert result["quality_score"] == 100.0
        assert result["completeness"]["score"] == 100.0
        assert result["anomaly_count"] == 0
        assert result["critical_anomalies"] == 0
        assert result["has_previous_data"] is False
        assert isinstance(result["checked_at"], str)

    async def test_quality_score_clamped_to_100(self) -> None:
        # No anomalies, full completeness, fresh -> score must cap at 100.
        data = {"a": 1, "b": 2}
        result = await run_quality_check("https://example.com/cap", data)
        assert result["quality_score"] == 100.0

    async def test_quality_score_floor_at_zero(self) -> None:
        # Many anomalies drive the score down; it must never go negative.
        # Force a previous run so anomalies are detected.
        await run_quality_check("https://example.com/floor", {"a": 1, "b": 2, "c": 3})
        result = await run_quality_check("https://example.com/floor", {"a": 1})
        assert result["quality_score"] >= 0
        assert result["has_previous_data"] is True
        assert result["anomaly_count"] >= 1

    async def test_expected_types_drives_schema_adherence(self) -> None:
        data = {"price": "not-a-number", "name": "ok"}
        result = await run_quality_check(
            "https://example.com/schema", data, expected_types={"price": int, "name": str}
        )
        assert result["schema_adherence"]["type_mismatches"] == 1
        expected = {"price": 1}
        assert result["schema_adherence"]["field_issues"] == expected

    async def test_corrupt_history_file_is_tolerated(self, tmp_path) -> None:
        # Write a corrupt JSON history file for a known URL, then run the
        # check — it must not raise and must treat previous as absent.
        url = "https://example.com/corrupt"
        url_hash = __import__("hashlib").sha256(url.encode()).hexdigest()[:16]
        (tmp_path / f"{url_hash}.json").write_text("{ not valid json !!!")
        result = await run_quality_check(url, {"a": 1})
        assert result["has_previous_data"] is False
        assert result["anomaly_count"] == 0

    async def test_history_is_persisted_for_next_run(self, tmp_path) -> None:
        url = "https://example.com/persist"
        await run_quality_check(url, {"a": 1})
        url_hash = __import__("hashlib").sha256(url.encode()).hexdigest()[:16]
        history_file = tmp_path / f"{url_hash}.json"
        assert history_file.exists()
        payload = json.loads(history_file.read_text())
        assert payload["url"] == url
        expected = {"a": 1}
        assert payload["data"] == expected
        assert "checked_at" in payload

    async def test_list_data_raises_in_compute_freshness(self) -> None:
        # [REVIEW] BUG: run_quality_check calls compute_freshness(data, ...)
        # which does data.get(key). When data is a list this used to raise
        # AttributeError instead of being handled. The null_rate/schema
        # guards only protect those two metrics, not freshness. Now list
        # input returns a neutral default instead of raising.
        result = await run_quality_check("https://example.com/list", [{"a": 1}])
        assert result["freshness"]["fresh"] is True
        assert result["freshness"]["age_seconds"] is None
        assert "cannot verify freshness" in result["freshness"]["note"]
