# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for page structure monitor."""

from unittest.mock import AsyncMock, patch

from structure_monitor import (
    check_selectors,
    get_structure_history,
    monitor_page_structure,
)


def test_check_selectors_empty() -> None:
    import asyncio

    result = asyncio.run(check_selectors("https://example.com", []))
    assert "selectors" in result


def test_get_structure_history_no_history() -> None:
    result = get_structure_history("https://nonexistent-page-test-123.com")
    assert result["has_history"] is False


def test_monitor_no_selectors() -> None:
    import asyncio

    mock_client = AsyncMock()
    mock_client.get.return_value.is_success = True
    mock_client.get.return_value.text = "<html><body>test</body></html>"

    with patch("structure_monitor.get_client", return_value=mock_client):
        result = asyncio.run(monitor_page_structure("https://example.com", []))
    assert "selectors" in result
    assert "changes" in result
