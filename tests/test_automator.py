"""Tests for automator.py — headless browser automation engine."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from pry.actors.automator import BrowserSession, PryAutomator


@pytest.fixture
def automator():
    return PryAutomator()


def test_init_playwright_not_available(automator: PryAutomator):
    assert hasattr(automator, "sessions")
    assert isinstance(automator.sessions, dict)


def test_check_available_skip():
    pass


def test_browser_session_defaults():
    bs = BrowserSession(id="test")
    assert bs.id == "test"
    assert bs.browser is None
    assert bs.page is None


def test_browser_session_with_values():
    import time

    now = time.time()
    bs = BrowserSession(
        id="full",
        browser="b",
        context="c",
        page="p",
        created_at=now,
        last_used=now,
        cookies_file="/tmp/cookies.json",
    )
    assert bs.cookies_file == "/tmp/cookies.json"


def test_automator_cleanup_loop_runs():
    """Cleanup loop can be created and cancelled."""

    async def _test():
        a = PryAutomator()
        a._cleanup_task = asyncio.create_task(a._cleanup_loop())
        await asyncio.sleep(0.05)
        a._cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await a._cleanup_task

    asyncio.run(_test())
