# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Focused unit tests for pry.commerce.pipelines_engine pure logic.

Exercises template resolution, JQ-style transforms, validation edge cases,
and the run_pipeline orchestration loop (abort + context propagation)
without touching the network-backed step types.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pry.commerce.pipelines_engine import (
    _apply_transform,
    _resolve_templates,
    run_pipeline,
    validate_pipeline,
)


class TestResolveTemplates:
    def test_substitutes_known_variable(self) -> None:
        assert _resolve_templates({"a": "{{x}}"}, {"x": 5}) == {"a": "5"}

    def test_leaves_unknown_placeholder_untouched(self) -> None:
        assert _resolve_templates({"a": "{{missing}}"}, {}) == {"a": "{{missing}}"}

    def test_resolves_dotted_key_as_flat_lookup(self) -> None:
        # Dotted names match a literal context key, not nested traversal.
        ctx = {"user.name": "ada"}
        assert _resolve_templates({"a": "{{user.name}}"}, ctx) == {"a": "ada"}

    def test_recurses_into_dicts(self) -> None:
        assert _resolve_templates({"n": {"k": "{{x}}"}}, {"x": 1}) == {"n": {"k": "1"}}

    def test_recurses_into_lists_of_dicts(self) -> None:
        result = _resolve_templates({"l": [{"k": "{{x}}"}, "plain"]}, {"x": 2})
        assert result == {"l": [{"k": "2"}, "plain"]}

    def test_passes_through_non_string_values(self) -> None:
        assert _resolve_templates({"z": 7}, {}) == {"z": 7}


class TestApplyTransform:
    DATA: dict[str, Any] = {"a": {"b": [10, 20, 30]}}  # noqa: RUF012 - test fixture, not a typed class contract

    def test_jsonpath_extracts_nested_value(self) -> None:
        assert _apply_transform(self.DATA, {"v": "$.a.b.1"}) == {"v": 20}

    def test_bare_dollar_returns_whole_document(self) -> None:
        assert _apply_transform(self.DATA, {"all": "$"}) == {"all": self.DATA}

    def test_literal_rule_is_copied(self) -> None:
        assert _apply_transform(self.DATA, {"lit": "const"}) == {"lit": "const"}

    def test_missing_path_yields_none(self) -> None:
        assert _apply_transform(self.DATA, {"m": "$.a.nope"}) == {"m": None}

    def test_out_of_range_index_yields_none(self) -> None:
        assert _apply_transform(self.DATA, {"o": "$.a.b.99"}) == {"o": None}

    def test_non_dict_transform_returns_input_unchanged(self) -> None:
        assert _apply_transform(self.DATA, "not-a-dict") == self.DATA


class TestValidatePipeline:
    def test_missing_required_input_reported(self) -> None:
        pipeline = {"steps": [{"id": "s", "type": "transform", "inputs": {"data": {}}}]}
        errors = validate_pipeline(pipeline)
        assert any("transform" in e for e in errors)

    def test_step_defaults_id_when_absent(self) -> None:
        pipeline = {"steps": [{"type": "nope", "inputs": {}}]}
        assert any("Unknown type" in e for e in validate_pipeline(pipeline))


class TestRunPipeline:
    def test_unknown_step_marks_failure(self) -> None:
        pipeline = {"id": "p1", "steps": [{"id": "s1", "type": "unknown", "inputs": {}}]}
        result = asyncio.run(run_pipeline(pipeline))
        assert result["failed"] is True
        assert result["failed_steps"] == 1

    def test_transform_step_writes_context_key(self) -> None:
        pipeline = {
            "steps": [
                {
                    "id": "t",
                    "type": "transform",
                    "inputs": {"data": {"k": 1}, "transform": {"r": "$.k"}},
                }
            ]
        }
        result = asyncio.run(run_pipeline(pipeline))
        assert result["successful_steps"] == 1
        assert "t.result" in result["context_keys"]

    def test_on_error_abort_stops_later_steps(self) -> None:
        pipeline = {
            "steps": [
                {"id": "bad", "type": "unknown", "inputs": {}, "on_error": "abort"},
                {"id": "after", "type": "unknown", "inputs": {}},
            ]
        }
        result = asyncio.run(run_pipeline(pipeline))
        assert result["completed_steps"] == 1
