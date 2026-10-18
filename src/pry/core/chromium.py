"""Pry — Chromium launch channel.

The runtime image ships exactly ONE Chromium build: Playwright's full
``chromium`` (installed with ``playwright install --no-shell``). The separate
``chromium-headless-shell`` binary is not shipped because it duplicates ~260 MB
of the same engine.

Playwright's default ``headless=True`` selects the headless-shell binary, so
every Playwright launch passes ``channel=CHROMIUM_CHANNEL`` instead. That runs
the full build in new-headless mode and keeps headed launches working with the
same single browser, i.e. no capability is traded for the size win.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

CHROMIUM_CHANNEL = "chromium"

__all__ = ["CHROMIUM_CHANNEL"]
