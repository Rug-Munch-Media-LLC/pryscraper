# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for cost analytics engine."""

from pry.commerce.costing import (
    DEFAULT_COST_TABLE,
    get_monthly_usage,
    record_usage,
)


def test_record_usage() -> None:
    result = record_usage("scrape_direct", {"url": "https://example.com"})
    assert result["operation"] == "scrape_direct"
    assert result["cost"] > 0
    assert "url" in result.get("metadata", {})


def test_record_usage_cost() -> None:
    result = record_usage("llm_call", quantity=2)
    expected = DEFAULT_COST_TABLE["llm_call"] * 2
    assert result["cost"] == round(expected, 6)


def test_get_monthly_usage() -> None:
    result = get_monthly_usage()
    assert "total_cost" in result
    assert "projected_monthly_cost" in result
    assert "breakdown" in result


def test_cost_table_keys() -> None:
    assert "scrape_direct" in DEFAULT_COST_TABLE
    assert "llm_call" in DEFAULT_COST_TABLE
    assert "vision_call" in DEFAULT_COST_TABLE
    assert "storage_gb_month" in DEFAULT_COST_TABLE
