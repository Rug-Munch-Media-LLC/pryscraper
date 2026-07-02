"""Tests for LLM fallback wiring in compliance, seo_monitor, reconciliation.

These tests verify that:
- The fallback path is INVOKED when the regex confidence is low (or fields are empty)
- The LLM result is MERGED into the regex result
- If the LLM call raises or returns nothing, the regex result is preserved
- If no LLM provider is configured, we degrade gracefully

The tests monkeypatch llm_features so we don't need a real LLM.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── compliance.py ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_llm_fallback_merges_into_tos_result():
    """When tos_result confidence is low, the LLM result should be merged in
    with the llm_enhanced flag set to True."""
    from compliance import run_compliance_check

    fake_llm = AsyncMock(
        return_value={
            "risk_level": "red",
            "confidence": "high",
            "risk_summary": "Strict scraping prohibition",
            "recommendation": "Contact site owner",
            "key_restrictions": ["no bots", "rate limited"],
            "llm_provider": "openrouter",
            "llm_cost_usd": 0.001,
        }
    )

    with patch("llm_features.llm_compliance_analyze", fake_llm):
        result = await run_compliance_check("https://example.com/")

    # The LLM should have been called
    assert fake_llm.called
    # The merged tos_result should have llm_enhanced: True
    tos = result.get("terms_of_service", {})
    assert tos.get("llm_enhanced") is True
    assert tos.get("classification") == "red"  # from the LLM
    assert tos.get("confidence") == "high"
    assert tos.get("llm_provider") == "openrouter"


@pytest.mark.asyncio
async def test_compliance_llm_fallback_preserves_result_on_error():
    """If the LLM call raises, the regex result should be preserved (no crash)."""
    from compliance import run_compliance_check

    fake_llm = AsyncMock(side_effect=RuntimeError("LLM down"))

    with patch("llm_features.llm_compliance_analyze", fake_llm):
        # Should not raise
        result = await run_compliance_check("https://example.com/")

    # Result should still be valid
    assert "url" in result
    assert "risk_level" in result


# ── seo_monitor.py ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seo_llm_enhancement_fills_empty_critical_fields():
    """When the regex pass leaves title/meta_description/h1 empty, the LLM
    should be invoked and its suggestions should fill the gaps."""
    from seo_monitor import analyze_seo

    fake_llm = AsyncMock(
        return_value={
            "title": "Pry - Web Intelligence",
            "meta_description": "Open any website with Pry's free API",
            "h1": "Web Scraping Made Simple",
            "llm_provider": "ollama",
            "llm_cost_usd": 0.0,
        }
    )

    # Patch the regex helpers to return empty
    with (
        patch("seo_monitor._get_title", return_value=""),
        patch("seo_monitor._get_meta_content", return_value=""),
        patch("seo_monitor._get_headings", return_value=[]),
        patch("seo_monitor._count_words", return_value=100),
        patch("seo_monitor._has_schema", return_value=False),
        patch("seo_monitor._get_hreflangs", return_value=[]),
        patch("seo_monitor._get_charset", return_value="utf-8"),
        patch("seo_monitor._get_attr", return_value=""),
        patch("seo_monitor._count_links", return_value=0),
        patch("llm_features.llm_seo_analyze", fake_llm),
        patch("client.get_client") as mock_get_client,
    ):
        # Mock the HTTP client to return a fake HTML response
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.text = "<html><body><h1>placeholder</h1></body></html>"
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html", "last-modified": ""}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        result = await analyze_seo("https://example.com/")

    assert fake_llm.called
    assert result["title"] == "Pry - Web Intelligence"
    assert result["llm_enhanced"] is True
    assert result["llm_provider"] == "ollama"


# ── reconciliation.py ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_llm_enhance_function_exists():
    """llm_enhance_reconciliation should be a callable that returns a dict."""
    from reconciliation import llm_enhance_reconciliation

    fake_llm = AsyncMock(return_value={"is_same_entity": True})

    with patch("llm_features.llm_entity_reconcile", fake_llm):
        result = await llm_enhance_reconciliation(
            [
                {"id": "1", "name": "Acme Widget", "confidence": 0.3, "group_id": "g1"},
                {"id": "2", "name": "Acme Widget Pro", "confidence": 0.4, "group_id": "g1"},
                {"id": "3", "name": "Other Product", "confidence": 0.95, "group_id": "g2"},
            ]
        )

    assert result["llm_enhanced"] is True
    # Only the low-confidence group (g1) should have been sent to the LLM
    assert fake_llm.call_count == 1
    assert result["low_confidence_groups"] == 1
    assert result["verified"] == 1


@pytest.mark.asyncio
async def test_reconciliation_llm_enhance_handles_no_low_confidence():
    """If all entities are high-confidence, the LLM should not be called."""
    from reconciliation import llm_enhance_reconciliation

    fake_llm = AsyncMock(return_value={"is_same_entity": True})

    with patch("llm_features.llm_entity_reconcile", fake_llm):
        result = await llm_enhance_reconciliation(
            [
                {"id": "1", "name": "A", "confidence": 0.9},
                {"id": "2", "name": "B", "confidence": 0.95},
            ]
        )

    assert not fake_llm.called
    assert result["llm_enhanced"] is False
    assert result["low_confidence_groups"] == 0


@pytest.mark.asyncio
async def test_reconciliation_llm_enhance_handles_llm_error():
    """If the LLM call raises, return a degraded result without crashing."""
    from reconciliation import llm_enhance_reconciliation

    fake_llm = AsyncMock(side_effect=ConnectionError("timeout"))

    with patch("llm_features.llm_entity_reconcile", fake_llm):
        result = await llm_enhance_reconciliation(
            [
                {"id": "1", "name": "A", "confidence": 0.3, "group_id": "g1"},
            ]
        )

    assert result["llm_enhanced"] is False
    assert "error" in result
