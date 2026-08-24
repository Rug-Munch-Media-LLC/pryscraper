# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pipeline builder."""

from pry.commerce.pipelines import (
    STEP_TYPES,
    list_pipelines,
    run_pipeline,
    save_pipeline,
    validate_pipeline,
)


def test_step_types_exist() -> None:
    assert "scrape" in STEP_TYPES
    assert "extract_css" in STEP_TYPES
    assert "quality_check" in STEP_TYPES
    assert "compliance_check" in STEP_TYPES
    assert "send_slack" in STEP_TYPES
    assert "send_email" in STEP_TYPES
    assert "conditional" in STEP_TYPES
    assert "delay" in STEP_TYPES
    assert "transform" in STEP_TYPES
    assert "export_training" in STEP_TYPES


def test_validate_empty() -> None:
    errors = validate_pipeline({"steps": []})
    assert len(errors) > 0


def test_validate_minimal() -> None:
    pipeline = {
        "name": "Test",
        "steps": [{"id": "step1", "type": "delay", "inputs": {"seconds": 1}}],
    }
    errors = validate_pipeline(pipeline)
    assert len(errors) == 0


def test_validate_invalid_type() -> None:
    pipeline = {"steps": [{"id": "bad", "type": "nonexistent", "inputs": {}}]}
    errors = validate_pipeline(pipeline)
    assert any("nonexistent" in e for e in errors)


def test_validate_duplicate_id() -> None:
    pipeline = {
        "steps": [
            {"id": "same", "type": "delay", "inputs": {"seconds": 1}},
            {"id": "same", "type": "delay", "inputs": {"seconds": 2}},
        ]
    }
    errors = validate_pipeline(pipeline)
    assert any("Duplicate" in e for e in errors)


def test_save_and_list() -> None:
    pipe = {
        "name": "Test Pipeline",
        "steps": [{"id": "s1", "type": "delay", "inputs": {"seconds": 1}}],
    }
    result = save_pipeline(pipe)
    assert result["success"] is True
    pipelines = list_pipelines()
    names = [p["name"] for p in pipelines]
    assert "Test Pipeline" in names


def test_run_delay() -> None:
    import asyncio

    pipeline = {
        "name": "Delay Test",
        "steps": [{"id": "wait", "type": "delay", "inputs": {"seconds": 0.1}}],
    }
    result = asyncio.run(run_pipeline(pipeline))
    assert result["successful_steps"] == 1
    assert result["failed"] is False
