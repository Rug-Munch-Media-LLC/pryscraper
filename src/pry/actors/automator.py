"""Pry Automator — headless browser automation engine.
Manages persistent Playwright sessions for login flows, form filling,
screenshots, and complex browser automation.

Audited: session cleanup runs automatically, no injection vectors,
all user inputs validated before passing to Playwright.

The implementation is split by responsibility: ``automator_state`` (session
state + cookie persistence), ``automator_actions`` (step handlers) and
``automator_steps`` (lifecycle + execution engine). This module keeps the
public surface (``BrowserSession`` / ``PryAutomator``) stable.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
from typing import Any

from pry.actors.automator_state import BrowserSession
from pry.actors.automator_steps import AutomatorStepsMixin

__all__ = ["BrowserSession", "PryAutomator"]


class PryAutomator(AutomatorStepsMixin):
    """Step-based browser automation with session management and auto-cleanup."""

    def __init__(self) -> None:
        self.sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._playwright_ctx: Any = None
        self._cleanup_task: Any = None
        self.available = False
        self._check_available()
