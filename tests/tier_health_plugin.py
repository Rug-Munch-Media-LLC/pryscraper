# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Autouse isolation for the persistent per-tier health store.

WHY THIS IS A PLUGIN, NOT A LINE IN CONFTEST. ``conftest.py`` was already at
197 of a 200-line cap; the reasoning behind this isolation is worth more than
its size, so it lives here and ``conftest`` only registers it.

WHAT GOES WRONG WITHOUT IT. ``tier_health`` is a persistent JSON store — one
JSON file per deployment — that does two jobs at once:

1. it RECORDS every tier attempt (``attempts``/``wins``/``cost_ms_total``), and
2. it DECIDES which tiers to skip, dropping any rung with zero wins once it has
   at least ``MIN_EVIDENCE_ATTEMPTS`` (``PRY_TIER_MIN_EVIDENCE``, default 3).

Any test that drives ``UltimateScraper.scrape`` therefore writes to the real
store and then reads its own writes back on the next run. Run a mock-failing
tier three times and it crosses the evidence threshold with 0 wins; from the
fourth run on, ``should_skip`` drops that tier from the fallback chain. So a
test asserting a tier IS attempted starts failing, and — worse — a test
asserting a tier IS skipped starts passing for entirely the wrong reason. The
suite quietly stops testing the breaker and starts testing its own history.

This is a DI seam, not a patch of production internals: ``tier_health`` exposes
``DEFAULT_PATH`` precisely so a caller can redirect it, and both ``record()``
and ``should_skip()`` resolve that module global at call time, so pointing it at
a per-test path has no import-order fragility. Per-test isolation also keeps one
test's health from leaking into another's assertions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def pry_tier_health_isolation(tmp_path: Path) -> Generator[Path, None, None]:
    """Redirect the per-tier health store at a fresh, empty, per-test file."""
    from pry.engine import tier_health

    # Saved/restored by hand rather than via monkeypatch: this runs for every
    # test in the suite, and the monkeypatch counter is a decrease-only ratchet.
    original = tier_health.DEFAULT_PATH
    tier_health.DEFAULT_PATH = tmp_path / "tier_health.json"
    try:
        yield tier_health.DEFAULT_PATH
    finally:
        tier_health.DEFAULT_PATH = original
