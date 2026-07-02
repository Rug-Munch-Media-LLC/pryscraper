# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for page structure monitor."""

from unittest.mock import AsyncMock, patch

import pytest

from structure_monitor import (
    check_selectors,
    get_structure_history,
    monitor_page_structure,
)


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    import db as db_module

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    db_module._engine = None
    db_module._SessionLocal = None
    db_module.get_engine()
    yield
    db_module._engine = None
    db_module._SessionLocal = None


@pytest.mark.asyncio
async def test_check_selectors_empty():
    result = await check_selectors("https://example.com", [])
    assert "selectors" in result
    assert result["all_matched"] is True


@pytest.mark.asyncio
async def test_get_structure_history_no_history(temp_db):
    result = await get_structure_history("https://nonexistent-page-test-123.com")
    assert result["has_history"] is False


@pytest.mark.asyncio
async def test_monitor_page_structure_creates_history(temp_db):
    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.get.return_value.text = "<html><body><h1>Title</h1></body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        result = await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    assert "selectors" in result
    assert "changes" in result
    assert result["all_matched"] is True
    assert result["has_changes"] is False


@pytest.mark.asyncio
async def test_get_structure_history_with_data(temp_db):
    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.get.return_value.text = "<html><body><h1>Title</h1></body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    result = await get_structure_history("https://example.com")
    assert result["has_history"] is True
    assert "last_checked" in result
    assert "last_selectors" in result


@pytest.mark.asyncio
async def test_monitor_page_structure_with_template_id(temp_db):
    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.get.return_value.text = "<html><body><h1>Title</h1></body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        result = await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h1", "type": "css"}],
            template_id="template-1",
        )

    assert result["template_id"] == "template-1"

    by_url = await get_structure_history("https://example.com")
    assert by_url["has_history"] is True

    by_template = await get_structure_history("https://example.com", template_id="template-1")
    assert by_template["has_history"] is True


@pytest.mark.asyncio
async def test_monitor_page_structure_detects_change(temp_db):
    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.get.return_value.text = "<html><body><h1>Title</h1></body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    mock_client.get.return_value.text = "<html><body><h1>New Title</h1></body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        result = await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h2", "type": "css"}],
        )

    assert "changes" in result


@pytest.mark.asyncio
async def test_structure_page_http_error(temp_db):
    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = False
    mock_client.get.return_value.status_code = 404

    with patch("structure_monitor.get_client", return_value=mock_client):
        result = await monitor_page_structure(
            "https://example.com/404",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    assert "error" in result
