# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for content monitors."""

from unittest.mock import AsyncMock, patch

import pytest

from pry.actors.monitor import (
    ChangeJudger,
    create_monitor,
    delete_monitor,
    list_monitors,
    run_monitor,
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
async def test_create_monitor(temp_db):
    result = await create_monitor("test-monitor", "https://example.com")
    assert result["name"] == "test-monitor"
    assert result["target_url"] == "https://example.com"
    assert len(result["id"]) == 12
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_create_monitor_with_all_options(temp_db):
    result = await create_monitor(
        "full-monitor",
        "https://example.com",
        schedule_cron="0 */12 * * *",
        goal="find price changes",
        webhook_url="https://hooks.example.com/notify",
        use_llm_judge=True,
    )
    assert result["name"] == "full-monitor"
    assert result["schedule_cron"] == "0 */12 * * *"
    assert result["goal"] == "find price changes"
    assert result["webhook_url"] == "https://hooks.example.com/notify"
    assert result["use_llm_judge"] is True


@pytest.mark.asyncio
async def test_list_monitors(temp_db):
    await create_monitor("m1", "https://example.com")
    await create_monitor("m2", "https://example.org")
    monitors = await list_monitors()
    assert len(monitors) == 2


@pytest.mark.asyncio
async def test_list_monitors_empty(temp_db):
    monitors = await list_monitors()
    assert monitors == []


@pytest.mark.asyncio
async def test_delete_monitor(temp_db):
    m = await create_monitor("to-delete", "https://example.com")
    assert await delete_monitor(m["id"]) is True
    monitors = await list_monitors()
    assert len(monitors) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_monitor(temp_db):
    assert await delete_monitor("nonexistent") is False


@pytest.mark.asyncio
async def test_run_monitor_with_change(temp_db):
    m = await create_monitor("change-test", "https://example.com")

    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = {"content": "new content here"}

    with patch("pry.engine.scraper.PryScraper", return_value=mock_scraper):
        result = await run_monitor(m["id"])

    assert result["monitor_id"] == m["id"]
    assert result["current_content_length"] > 0


@pytest.mark.asyncio
async def test_run_monitor_no_change(temp_db):
    m = await create_monitor("no-change", "https://example.com")

    mock_scraper = AsyncMock()
    mock_scraper.scrape.return_value = {"content": ""}

    with patch("pry.engine.scraper.PryScraper", return_value=mock_scraper):
        result = await run_monitor(m["id"])

    assert result["changed"] is False


@pytest.mark.asyncio
async def test_run_monitor_not_found(temp_db):
    result = await run_monitor("nonexistent")
    assert "error" in result


@pytest.mark.asyncio
async def test_run_monitor_scrape_error(temp_db):
    m = await create_monitor("scrape-error", "https://example.com")

    mock_scraper = AsyncMock()
    mock_scraper.scrape.side_effect = ValueError("connection refused")

    with patch("pry.engine.scraper.PryScraper", return_value=mock_scraper):
        result = await run_monitor(m["id"])

    assert "error" in result


async def _judge(previous: str, current: str, goal: str = "") -> dict:
    j = ChangeJudger()
    return await j.judge(previous, current, goal)


def test_judger_no_goal_no_change() -> None:
    import asyncio

    result = asyncio.run(_judge("same content", "same content"))
    assert result["meaningful"] is False


def test_judger_no_goal_with_change() -> None:
    import asyncio

    result = asyncio.run(_judge("old content", "new content"))
    assert result["meaningful"] is True


def test_judger_with_goal_relevant() -> None:
    import asyncio

    result = asyncio.run(
        _judge("Company has 10 employees", "Company has 500 employees", goal="employee count")
    )
    assert result["meaningful"] is True


def test_judger_with_goal_irrelevant() -> None:
    import asyncio

    result = asyncio.run(
        _judge("Company has 10 employees", "Company is located in NY", goal="employee count")
    )
    assert result["meaningful"] is False


def test_judger_empty_previous() -> None:
    import asyncio

    result = asyncio.run(_judge("", "New content here"))
    assert result["meaningful"] is True
