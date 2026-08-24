# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for adaptive freshness scheduling."""

from pry.commerce.freshness import (
    calculate_adaptive_frequency,
    check_content_changed,
    compute_content_hash,
    record_check_result,
)


def test_content_hash_consistent() -> None:
    h1 = compute_content_hash("Hello   World")
    h2 = compute_content_hash("Hello World")
    assert h1 == h2  # Whitespace normalization


def test_content_hash_differs() -> None:
    h1 = compute_content_hash("Hello World")
    h2 = compute_content_hash("Hello World!")
    assert h1 != h2


def test_check_content_changed_new_url() -> None:
    import asyncio
    import uuid

    unique_url = f"https://example.com/fresh-test-{uuid.uuid4().hex[:8]}"
    result = asyncio.run(check_content_changed(unique_url, "content"))
    assert result["is_new"] is True
    assert result["changed"] is True


def test_calculate_frequency_new() -> None:
    result = calculate_adaptive_frequency("https://example.com", base_interval_minutes=60)
    assert "suggested_interval_minutes" in result
    assert result["volatility"] in ("high", "medium", "low")


def test_record_and_frequency() -> None:
    # Record some changes
    record_check_result("https://example.com/volatile", True)
    record_check_result("https://example.com/volatile", True)
    record_check_result("https://example.com/volatile", True)
    result = calculate_adaptive_frequency("https://example.com/volatile", base_interval_minutes=60)
    assert result["changes_detected"] >= 3
