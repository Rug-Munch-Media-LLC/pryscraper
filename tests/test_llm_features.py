# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for llm_features — the AI-forward feature layer.

Every feature routes through ``LLMRegistry.complete_json`` with a PROMPTS
registry schema; the registry/HTTP layer is mocked here (see
``test_llm_providers.py`` for fallback/retry/stream coverage).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.api.llm_features import (
    llm_anomaly_detect,
    llm_compliance_analyze,
    llm_entity_reconcile,
    llm_pii_detect,
    llm_seo_analyze,
)
from pry.intelligence.llm.prompts import PROMPTS, render_prompt


@pytest.fixture
def mock_registry() -> MagicMock:
    """Registry whose complete_json is mocked; no real LLM calls."""
    reg = MagicMock()
    reg.complete_json = AsyncMock(return_value={"ok": True})
    with patch("pry.api.llm_features.get_registry", return_value=reg):
        yield reg


# ── compliance ────────────────────────────────────────────────────


async def test_compliance_analyze_routes_through_complete_json(mock_registry: MagicMock) -> None:
    result = await llm_compliance_analyze("Some terms text", url="https://example.com")
    expected = {"ok": True}
    assert result == expected
    mock_registry.complete_json.assert_awaited_once()
    call = mock_registry.complete_json.call_args
    assert "Terms of Service" in call.args[0]
    assert "https://example.com" in call.args[0]
    assert call.kwargs["schema"] == PROMPTS["compliance_analyze"]["schema"]
    assert call.kwargs["fallback"]["risk_level"] == "unknown"


async def test_compliance_analyze_empty_text_short_circuits(mock_registry: MagicMock) -> None:
    result = await llm_compliance_analyze("")
    expected = {"risk_level": "unknown", "reason": "No ToS text provided"}
    assert result == expected
    mock_registry.complete_json.assert_not_awaited()


async def test_compliance_analyze_returns_fallback_on_exception(mock_registry: MagicMock) -> None:
    mock_registry.complete_json.side_effect = RuntimeError("LLM down")
    result = await llm_compliance_analyze("Some terms text")
    assert result["risk_level"] == "unknown"
    assert "error" in result


# ── seo ───────────────────────────────────────────────────────────


async def test_seo_analyze_routes_through_complete_json(mock_registry: MagicMock) -> None:
    result = await llm_seo_analyze(
        "https://example.com", "<h1>Widget</h1>", target_keywords=["widget", "gadget"]
    )
    expected = {"ok": True}
    assert result == expected
    call = mock_registry.complete_json.call_args
    assert "widget, gadget" in call.args[0]
    assert call.kwargs["schema"] == PROMPTS["seo_analyze"]["schema"]


async def test_seo_analyze_empty_content_short_circuits(mock_registry: MagicMock) -> None:
    result = await llm_seo_analyze("https://example.com", "")
    expected = {"score": 0, "recommendations": []}
    assert result == expected
    mock_registry.complete_json.assert_not_awaited()


# ── entity reconcile ──────────────────────────────────────────────


async def test_entity_reconcile_routes_through_complete_json(mock_registry: MagicMock) -> None:
    records = [{"id": "1", "name": "Acme"}, {"id": "2", "name": "Acme Pro"}]
    result = await llm_entity_reconcile(records, vertical="product")
    expected = {"ok": True}
    assert result == expected
    call = mock_registry.complete_json.call_args
    assert "product" in call.args[0]
    assert '"id": "1"' in call.args[0]
    assert call.kwargs["schema"] == PROMPTS["entity_reconcile"]["schema"]
    assert call.kwargs["fallback"]["entities"] == records


async def test_entity_reconcile_single_record_short_circuits(mock_registry: MagicMock) -> None:
    result = await llm_entity_reconcile([{"id": "1"}])
    expected = {"entities": [{"id": "1"}], "matches": []}
    assert result == expected
    mock_registry.complete_json.assert_not_awaited()


# ── pii ───────────────────────────────────────────────────────────


async def test_pii_detect_routes_through_complete_json(mock_registry: MagicMock) -> None:
    text = "Contact sales@example.com for details" * 5
    result = await llm_pii_detect(text)
    expected = {"ok": True}
    assert result == expected
    call = mock_registry.complete_json.call_args
    assert "sales@example.com" in call.args[0]
    assert call.kwargs["schema"] == PROMPTS["pii_detect"]["schema"]
    assert call.kwargs["fallback"]["redacted_text"] == text


async def test_pii_detect_short_text_short_circuits(mock_registry: MagicMock) -> None:
    result = await llm_pii_detect("short")
    expected = {"pii_found": [], "redacted_text": "short"}
    assert result == expected
    mock_registry.complete_json.assert_not_awaited()


# ── anomaly ───────────────────────────────────────────────────────


async def test_anomaly_detect_routes_through_complete_json(mock_registry: MagicMock) -> None:
    historical = [{"price": 10}, {"price": 11}]
    current = {"price": 5}
    result = await llm_anomaly_detect(historical, current, field="price")
    expected = {"ok": True}
    assert result == expected
    call = mock_registry.complete_json.call_args
    assert "price" in call.args[0]
    assert '"price": 5' in call.args[0]
    assert call.kwargs["schema"] == PROMPTS["anomaly_detect"]["schema"]
    assert call.kwargs["fallback"]["is_anomaly"] is False


async def test_anomaly_detect_missing_data_short_circuits(mock_registry: MagicMock) -> None:
    result = await llm_anomaly_detect([], {"price": 5})
    expected = {"anomaly": False, "reason": "Insufficient data"}
    assert result == expected
    mock_registry.complete_json.assert_not_awaited()


# ── prompts registry ──────────────────────────────────────────────


def test_prompts_registry_entries_complete() -> None:
    expected = {
        "compliance_analyze",
        "seo_analyze",
        "entity_reconcile",
        "pii_detect",
        "anomaly_detect",
    }
    assert set(PROMPTS) == expected
    for name in expected:
        spec = PROMPTS[name]
        assert "user" in spec
        assert "schema" in spec
        assert "system" in spec
        assert "max_tokens" in spec
        assert "temperature" in spec


def test_render_prompt_escapes_literal_braces() -> None:
    rendered = render_prompt("pii_detect", text="x" * 60)
    assert '{"text": "the PII"' in rendered
    assert rendered.count("{text") == 0  # placeholder was substituted
    seo = render_prompt("seo_analyze", keywords="k", url="u", content="c")
    assert "{keyword:" in seo


def test_render_prompt_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        render_prompt("does_not_exist", text="x")
