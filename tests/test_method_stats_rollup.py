"""Tests for the batch-rollup arithmetic behind the method-memory store.

Pure functions, no DB — the arithmetic is split out precisely so it can be
verified without standing anything up.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import pytest

from pry.engine.method_stats_rollup import collapse_updates, merge_percentile, percentile_ms
from pry.engine.method_stats_writer import MethodStatUpdate


def test_percentile_ms_empty_is_zero() -> None:
    assert percentile_ms([], 0.5) == 0.0
    assert percentile_ms([0.0, 0.0], 0.95) == 0.0


def test_percentile_ms_nearest_rank() -> None:
    samples = [100.0, 200.0, 300.0, 400.0, 5000.0]
    assert percentile_ms(samples, 0.5) == 300.0
    assert percentile_ms(samples, 0.95) == 5000.0


def test_collapse_updates_folds_a_batch() -> None:
    updates = [
        MethodStatUpdate("a.com", "m", True, 100.0, 0.01, "", 10.0),
        MethodStatUpdate("a.com", "m", False, 300.0, 0.01, "captcha", 11.0),
        MethodStatUpdate("a.com", "m", True, 200.0, 0.01, "", 12.0),
    ]
    d = collapse_updates(updates)
    assert d["attempts"] == 3
    assert d["wins"] == 2
    assert d["cost"] == pytest.approx(0.03)
    assert d["p50"] == 200.0
    assert d["p95"] == 300.0
    assert d["block"] == "captcha"


def test_merge_percentile_weights_toward_stored() -> None:
    assert merge_percentile(0, 500.0) == 500.0
    assert merge_percentile(None, 500.0) == 500.0
    assert merge_percentile(1000.0, 0.0) == 1000.0
    assert merge_percentile(1000.0, 500.0) == pytest.approx(850.0)
