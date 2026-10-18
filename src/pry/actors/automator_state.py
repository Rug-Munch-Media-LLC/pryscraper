"""Pry Automator — session state and cookie persistence primitives."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

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


def cookies_path(session_id: str) -> str:
    """Create the sessions dir and return the cookie file path for a session."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return f"{SESSIONS_DIR}/{session_id}.json"


async def load_cookies(context: Any, cookies_file: str) -> None:
    """Restore persisted cookies onto a fresh browser context, if any exist."""
    if not os.path.exists(cookies_file):  # noqa: ASYNC240 - tiny cookie file, session lifecycle
        return
    try:
        with open(cookies_file) as f:  # noqa: ASYNC230 - tiny cookie JSON (<KB), low-frequency
            cookies = json.load(f)
        await context.add_cookies(cookies)
    except OSError as e:
        logger.warning("session_cookie_load_failed", extra={"error": str(e)[:160]})


async def persist_cookies(context: Any, cookies_file: str) -> None:
    """Write the current context cookies to disk (best effort)."""
    try:
        cookies = await context.cookies()
        with open(cookies_file, "w") as f:  # noqa: ASYNC230 - tiny cookie JSON (<KB), low-frequency
            json.dump(cookies, f)
    except OSError as e:
        logger.warning("session_cookie_persist_failed", extra={"error": str(e)[:160]})
