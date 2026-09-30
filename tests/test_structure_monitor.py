# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for page structure monitor."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from pry.actors.structure_monitor import (
    check_selectors,
    get_structure_history,
    monitor_page_structure,
)


def _response(*, ok: bool = True, text: str = "", status: int = 200) -> httpx.Response:
    """A real httpx.Response so the guard's own response handling is exercised.

    The actor now fetches through ``guard_get``, so mocking ``client.get`` no
    longer controls the response the actor sees: an ``AsyncMock`` response has a
    truthy ``is_redirect`` and a mock ``.url``, which sends ``safe_get`` into
    its redirect loop with non-str arguments. Patching ``guard_get`` with a
    real ``httpx.Response`` keeps each test asserting what it is actually about
    (snapshot history, change detection, an upstream error) instead of which
    seam happens to issue the request.
    """
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("GET", "https://example.com"),
    )


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    """Force a brand-new in-memory SQLite engine for every test.

    `structure_monitor` reads from the module-level `db._engine`. Without
    this fixture a previous test that committed StructureSnapshot rows
    (e.g. via `temp_db` pointing at a tmp_path sqlite file) leaks state
    into the next test that doesn't use the `temp_db` fixture
    (`test_check_selectors_empty`). Yielding a private :memory: engine
    per-test guarantees isolation regardless of import order.

    Also resets the shared `client.http_client` so an httpx.AsyncClient
    bound to a closed event loop (from a prior test) doesn't surface as
    RuntimeError on the next test that hits the network.
    """
    from sqlalchemy import create_engine

    import pry.core.client as client_module
    import pry.core.db as db_module

    monkeypatch.setenv("PRY_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PRY_DATA_DIR", "/tmp")
    db_module._engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    db_module._SessionLocal = None
    # Recreate tables on the new engine.
    from pry.core.db import Base

    Base.metadata.create_all(db_module._engine)
    client_module.http_client = None
    yield
    db_module._engine = None
    db_module._SessionLocal = None
    client_module.http_client = None


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    import pry.core.db as db_module

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
@respx.mock
async def test_check_selectors_empty():
    # Hermetic: never hit the live network. The empty selector list must
    # short-circuit to all_matched=True regardless of page content.
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, text="<html><body><p>x</p></body></html>")
    )
    result = await check_selectors("https://example.com", [])
    assert result["selectors"] == []
    assert result["all_matched"] is True


@pytest.mark.asyncio
async def test_get_structure_history_no_history(temp_db):
    result = await get_structure_history("https://nonexistent-page-test-123.com")
    assert result["has_history"] is False


@pytest.mark.asyncio
async def test_monitor_page_structure_creates_history(temp_db):
    page = _response(text="<html><body><h1>Title</h1></body></html>")
    with patch("pry.actors.structure_monitor.guard_get", AsyncMock(return_value=page)):
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
    page = _response(text="<html><body><h1>Title</h1></body></html>")
    with patch("pry.actors.structure_monitor.guard_get", AsyncMock(return_value=page)):
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
    page = _response(text="<html><body><h1>Title</h1></body></html>")
    with patch("pry.actors.structure_monitor.guard_get", AsyncMock(return_value=page)):
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
    page = _response(text="<html><body><h1>Title</h1></body></html>")
    with patch("pry.actors.structure_monitor.guard_get", AsyncMock(return_value=page)):
        await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    moved = _response(text="<html><body><h1>New Title</h1></body></html>")
    with patch("pry.actors.structure_monitor.guard_get", AsyncMock(return_value=moved)):
        result = await monitor_page_structure(
            "https://example.com",
            [{"name": "title", "selector": "h2", "type": "css"}],
        )

    assert "changes" in result


@pytest.mark.asyncio
async def test_structure_page_http_error(temp_db):
    with patch(
        "pry.actors.structure_monitor.guard_get",
        AsyncMock(return_value=_response(ok=False, status=404)),
    ):
        result = await monitor_page_structure(
            "https://example.com/404",
            [{"name": "title", "selector": "h1", "type": "css"}],
        )

    assert "error" in result
