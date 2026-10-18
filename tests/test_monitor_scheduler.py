# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Scheduler and monitor-run control tests.

Covers: single-flight claim (no double runs), retry + error state on scrape
failure, and a scheduler tick that runs a due monitor without any HTTP call.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from pry.actors.monitor import create_monitor, list_monitors, run_monitor
from pry.core.db import Monitor, MonitorRun, session_scope


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    import pry.core.db as db_module

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_MONITOR_RETRY_BACKOFF_S", "0")
    db_module._engine = None
    db_module._SessionLocal = None
    db_module.get_engine()
    # Schema authority is Alembic; get_engine() deliberately does not
    # create_all. A test that needs tables must ask for them.
    from pry.core.db import Base

    Base.metadata.create_all(db_module.get_engine())
    yield tmp_path
    db_module._engine = None
    db_module._SessionLocal = None


def _runs(monitor_id: str) -> list[MonitorRun]:
    with session_scope() as s:
        return list(s.query(MonitorRun).filter(MonitorRun.monitor_id == monitor_id).all())


def test_import_does_not_start_the_loop():
    from pry.actors import scheduler

    assert scheduler._scheduler_task is None


@pytest.mark.asyncio
async def test_concurrent_runs_claim_once(temp_db):
    monitor = await create_monitor("claimed", "https://example.com/page")
    scrape = AsyncMock(return_value={"content": "hello"})

    with patch("pry.engine.scraper.PryScraper.scrape", scrape):
        results = await asyncio.gather(run_monitor(monitor["id"]), run_monitor(monitor["id"]))

    assert scrape.await_count == 1, "only one caller may scrape"
    assert len(_runs(monitor["id"])) == 1, "exactly one MonitorRun row"
    assert any(r.get("skipped") for r in results), "second caller was claimed out"


@pytest.mark.asyncio
async def test_scrape_failure_retries_then_errors(temp_db, monkeypatch):
    monkeypatch.setenv("PRY_MONITOR_MAX_ATTEMPTS", "2")
    monitor = await create_monitor("failing", "https://broken.example/page")
    scrape = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("pry.engine.scraper.PryScraper.scrape", scrape):
        result = await run_monitor(monitor["id"])

    assert "error" in result
    assert scrape.await_count == 2, "one initial attempt plus exactly one retry"

    runs = _runs(monitor["id"])
    assert len(runs) == 1
    assert runs[0].status == "error"

    monitors = {m["id"]: m for m in await list_monitors()}
    assert monitors[monitor["id"]]["status"] == "error"

    dlq = temp_db / "monitor_dlq" / "dead_letter.jsonl"
    assert dlq.exists()
    assert monitor["id"] in dlq.read_text()


@pytest.mark.asyncio
async def test_scheduler_tick_runs_due_monitor_without_http(temp_db):
    from pry.actors.scheduler import tick

    monitor = await create_monitor("due", "https://example.com/feed", schedule_cron="* * * * *")
    with session_scope() as s:
        row = s.query(Monitor).filter(Monitor.monitor_id == monitor["id"]).first()
        row.last_run_at = datetime.now(UTC) - timedelta(hours=2)

    scrape = AsyncMock(return_value={"content": "fresh content"})
    with patch("pry.engine.scraper.PryScraper.scrape", scrape):
        result = await tick(timeout_s=5)

    assert result["due"] == 1
    assert scrape.await_count == 1
    assert result["results"][0]["monitor_id"] == monitor["id"]
