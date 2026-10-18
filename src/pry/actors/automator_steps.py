"""Pry Automator — session lifecycle and step execution engine."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import contextlib
import os
import time
import uuid
from typing import Any, ClassVar

from pry.actors import automator_actions as actions
from pry.actors.automator_state import (
    SESSION_CLEANUP_INTERVAL,
    SESSION_MAX_AGE,
    BrowserSession,
    cookies_path,
    load_cookies,
    persist_cookies,
)
from pry.core.chromium import CHROMIUM_CHANNEL


class AutomatorStepsMixin:
    """Step-based browser automation with session management and auto-cleanup."""

    _STEP_HANDLERS: ClassVar[dict[str, Any]] = {
        "navigate": actions.step_navigate,
        "click": actions.step_click,
        "type": actions.step_type,
        "select": actions.step_select,
        "wait": actions.step_wait,
        "wait_for_selector": actions.step_wait_for_selector,
        "screenshot": actions.step_screenshot,
        "extract": actions.step_extract,
        "scroll": actions.step_scroll,
        "submit": actions.step_submit,
        "evaluate": actions.step_evaluate,
    }

    async def _start_cleanup(self) -> None:
        """Start cleanup loop (called after event loop is running)."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def _check_available(self) -> None:
        import shutil

        self.available = shutil.which("playwright") is not None

    async def _ensure_playwright(self) -> Any:
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright_ctx = async_playwright()
            self._playwright = await self._playwright_ctx.start()
        return self._playwright

    async def _cleanup_loop(self) -> None:
        """Periodically clean up stale sessions to prevent memory leaks."""
        while True:
            await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
            with contextlib.suppress(Exception):
                await self._cleanup_stale_sessions()

    async def _launch_session(self, session_id: str | None, headless: bool, viewport: dict | None):
        """Launch a browser/context/page triple and register the session."""
        pw = await self._ensure_playwright()
        browser = await pw.chromium.launch(headless=headless, channel=CHROMIUM_CHANNEL)
        context = await browser.new_context(
            viewport=viewport or {"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()

        sid = session_id or f"session_{uuid.uuid4().hex[:12]}"
        session = BrowserSession(
            id=sid,
            browser=browser,
            context=context,
            page=page,
            created_at=time.time(),
            last_used=time.time(),
            cookies_file=cookies_path(sid),
        )
        await load_cookies(context, session.cookies_file)
        self.sessions[sid] = session
        return session

    async def _get_or_create_session(
        self, session_id: str | None = None, headless: bool = True, viewport: dict | None = None
    ) -> BrowserSession:
        async with self._lock:
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                session.last_used = time.time()
                return session
            return await self._launch_session(session_id, headless, viewport)

    async def run_steps(
        self,
        steps: list[dict[str, Any]],
        session_id: str | None = None,
        headless: bool = True,
        viewport: dict | None = None,
    ) -> dict[str, Any]:
        """Execute automation steps. All user inputs are validated before use."""
        if not steps:
            return {"error": "No steps provided", "steps": []}
        await self._start_cleanup()

        session = await self._get_or_create_session(session_id, headless, viewport)
        page = session.page
        results: list[dict[str, Any]] = []

        try:
            for step in steps:
                action = step.get("action", "")
                result: dict[str, Any] = {"action": action, "status": "ok"}
                handler = self._STEP_HANDLERS.get(action)
                if handler is None:
                    result["status"] = "error"
                    result["error"] = f"Unknown action: {action}"
                else:
                    await handler(page, step, result)
                results.append(result)

            await persist_cookies(session.context, session.cookies_file)
            return {
                "session_id": session.id,
                "steps": results,
                "final_url": page.url,
                "final_title": await page.title(),
            }
        except OSError as e:
            return {
                "session_id": session.id,
                "steps": results,
                "error": str(e),
                "final_url": page.url if page else "",
            }

    async def create_session(
        self, url: str, cookies: list | None = None, persist: bool = True
    ) -> str:
        session = await self._get_or_create_session()
        if cookies:
            with contextlib.suppress(Exception):
                await session.context.add_cookies(cookies)
        await session.page.goto(url, wait_until="networkidle")
        return session.id

    async def destroy_session(self, session_id: str) -> None:
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions.pop(session_id)
                with contextlib.suppress(OSError):
                    await session.browser.close()
                if os.path.exists(session.cookies_file):  # noqa: ASYNC240 - session lifecycle
                    with contextlib.suppress(OSError):
                        os.remove(session.cookies_file)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "age_seconds": int(time.time() - s.created_at),
                "idle_seconds": int(time.time() - s.last_used),
            }
            for s in self.sessions.values()
        ]

    async def _cleanup_stale_sessions(self) -> None:
        async with self._lock:
            now = time.time()
            stale = [sid for sid, s in self.sessions.items() if now - s.last_used > SESSION_MAX_AGE]
            for sid in stale:
                session = self.sessions.pop(sid)
                with contextlib.suppress(OSError):
                    await session.browser.close()
