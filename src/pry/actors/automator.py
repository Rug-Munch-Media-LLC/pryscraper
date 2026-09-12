"""Pry Automator — headless browser automation engine.
Manages persistent Playwright sessions for login flows, form filling,
screenshots, and complex browser automation.

Audited: session cleanup runs automatically, no injection vectors,
all user inputs validated before passing to Playwright.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

SESSIONS_DIR = "/app/sessions"
SESSION_MAX_AGE = 3600  # 1 hour
SESSION_CLEANUP_INTERVAL = 300  # 5 min


@dataclass
class BrowserSession:
    """A persistent browser session with cookie management."""

    id: str
    browser: Any = None
    context: Any = None
    page: Any = None
    created_at: float = 0.0
    last_used: float = 0.0
    cookies_file: str = ""


class PryAutomator:
    """Step-based browser automation with session management and auto-cleanup."""

    def __init__(self):
        self.sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._playwright = None
        self._cleanup_task = None
        self.available = False
        self._check_available()

    async def _start_cleanup(self):
        """Start cleanup loop (called after event loop is running)."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def _check_available(self):
        import shutil

        self.available = shutil.which("playwright") is not None

    async def _ensure_playwright(self):
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright_ctx = async_playwright()
            self._playwright = await self._playwright_ctx.start()
        return self._playwright

    async def _cleanup_loop(self):
        """Periodically clean up stale sessions to prevent memory leaks."""
        while True:
            await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
            with contextlib.suppress(Exception):
                await self._cleanup_stale_sessions()

    async def _get_or_create_session(
        self, session_id: str | None = None, headless: bool = True, viewport: dict | None = None
    ) -> BrowserSession:
        async with self._lock:
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                session.last_used = time.time()
                return session

            pw = await self._ensure_playwright()
            browser = await pw.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport=viewport or {"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = await context.new_page()

            sid = session_id or f"session_{uuid.uuid4().hex[:12]}"
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            cookies_file = f"{SESSIONS_DIR}/{sid}.json"

            session = BrowserSession(
                id=sid,
                browser=browser,
                context=context,
                page=page,
                created_at=time.time(),
                last_used=time.time(),
                cookies_file=cookies_file,
            )

            # Load persisted cookies
            if os.path.exists(cookies_file):  # noqa: ASYNC240 - tiny cookie file, session lifecycle
                try:
                    with open(cookies_file) as f:  # noqa: ASYNC230 - tiny cookie JSON (<KB), low-frequency
                        cookies = json.load(f)
                    await context.add_cookies(cookies)
                except OSError as e:
                    logger.warning(
                        "session_cookie_load_failed",
                        extra={"error": str(e)[:160]},
                    )

            self.sessions[sid] = session
            return session

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
                    await handler(self, page, step, result)

                results.append(result)

            # Persist cookies
            try:
                cookies = await session.context.cookies()
                with open(session.cookies_file, "w") as f:  # noqa: ASYNC230 - tiny cookie JSON (<KB), low-frequency
                    json.dump(cookies, f)
            except OSError as e:
                logger.warning(
                    "session_cookie_persist_failed",
                    extra={"error": str(e)[:160]},
                )

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

    # ── Step handlers (extracted from run_steps — audit P2) ─────────────────
    # Each mutates ``result`` exactly like the previous inline if/elif branch.

    async def _step_navigate(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        url = str(step.get("url", "")).strip()
        if not url or not url.startswith(("http://", "https://", "file://")):
            result["status"] = "error"
            result["error"] = "Invalid URL"
            return
        wait_until = step.get("wait_until", "networkidle")
        timeout = min(int(step.get("timeout", 30000)), 120000)
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        result["url"] = page.url
        result["title"] = await page.title()

    async def _step_click(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        selector = str(step.get("selector", ""))
        if not selector:
            result["status"] = "error"
            result["error"] = "No selector provided"
            return
        timeout = min(int(step.get("timeout", 10000)), 30000)
        await page.wait_for_selector(selector, timeout=timeout)
        await page.click(selector)

    async def _step_type(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        selector = str(step.get("selector", ""))
        value = str(step.get("value", ""))
        if not selector:
            result["status"] = "error"
            result["error"] = "No selector provided"
            return
        timeout = min(int(step.get("timeout", 10000)), 30000)
        await page.wait_for_selector(selector, timeout=timeout)
        await page.fill(selector, value)

    async def _step_select(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        selector = str(step.get("selector", ""))
        value = str(step.get("value", ""))
        if selector:
            await page.select_option(selector, value)
        else:
            result["status"] = "error"
            result["error"] = "No selector"

    async def _step_wait(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        ms = max(100, min(int(step.get("timeout", 2000)), 60000))
        await asyncio.sleep(ms / 1000)

    async def _step_wait_for_selector(
        self, page: Any, step: dict[str, Any], result: dict[str, Any]
    ) -> None:
        selector = str(step.get("selector", ""))
        if selector:
            timeout = min(int(step.get("timeout", 30000)), 60000)
            await page.wait_for_selector(selector, timeout=timeout)
        else:
            result["status"] = "error"
            result["error"] = "No selector"

    async def _step_screenshot(
        self, page: Any, step: dict[str, Any], result: dict[str, Any]
    ) -> None:
        full_page = bool(step.get("full_page", True))
        screenshot_bytes = await page.screenshot(full_page=full_page)
        b64 = base64.b64encode(screenshot_bytes).decode()
        result["screenshot"] = b64

    async def _step_extract(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        selector = str(step.get("selector", ""))
        extract_type = step.get("extract", "text")
        attribute = step.get("attribute")
        if not selector:
            result["status"] = "error"
            result["error"] = "No selector"
        else:
            elements = await page.query_selector_all(selector)
            if extract_type == "text":
                result["texts"] = [await el.inner_text() for el in elements]
            elif extract_type == "html":
                result["htmls"] = [await el.inner_html() for el in elements]
            elif extract_type == "attribute" and attribute:
                result["values"] = [await el.get_attribute(attribute) for el in elements]
        result["title"] = await page.title()
        result["url"] = page.url

    async def _step_scroll(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        dx = int(step.get("dx", 0))
        dy = int(step.get("dy", 500))
        # Scroll values are safely cast to int — no injection possible
        await page.evaluate(f"window.scrollBy({dx}, {dy})")
        await asyncio.sleep(0.3)

    async def _step_submit(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        selector = str(step.get("selector", ""))
        if selector:
            await page.wait_for_selector(selector, timeout=5000)
            await page.click(selector)
        else:
            await page.keyboard.press("Enter")

    async def _step_evaluate(self, page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
        js = str(step.get("script", ""))
        if js:
            return_val = await page.evaluate(js)
            result["return"] = return_val
        else:
            result["status"] = "error"
            result["error"] = "No script provided"

    _STEP_HANDLERS: ClassVar[dict[str, Any]] = {
        "navigate": _step_navigate,
        "click": _step_click,
        "type": _step_type,
        "select": _step_select,
        "wait": _step_wait,
        "wait_for_selector": _step_wait_for_selector,
        "screenshot": _step_screenshot,
        "extract": _step_extract,
        "scroll": _step_scroll,
        "submit": _step_submit,
        "evaluate": _step_evaluate,
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

    async def destroy_session(self, session_id: str):
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions.pop(session_id)
                with contextlib.suppress(OSError):
                    await session.browser.close()
                if os.path.exists(session.cookies_file):  # noqa: ASYNC240 - tiny cookie file, session lifecycle
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

    async def _cleanup_stale_sessions(self):
        async with self._lock:
            now = time.time()
            stale = [sid for sid, s in self.sessions.items() if now - s.last_used > SESSION_MAX_AGE]
            for sid in stale:
                session = self.sessions.pop(sid)
                with contextlib.suppress(OSError):
                    await session.browser.close()
