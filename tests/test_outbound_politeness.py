# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Outbound politeness tests: cap, Retry-After, and migrated call sites."""

from __future__ import annotations

import asyncio
import pathlib
import re

from pry.core import outbound_politeness as op

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "pry"


def test_delay_is_capped_for_every_attempt():
    for attempt in (1, 5, 12, 40):
        delay = op._delay(attempt)
        assert 0 < delay <= op.CAP_SECONDS * 1.25


def test_retry_after_is_honoured_and_capped():
    assert op._delay(1, retry_after=5) == 5
    assert op._delay(1, retry_after=999) == op.CAP_SECONDS


def test_outbound_backoff_sleeps_the_returned_delay(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(op.asyncio, "sleep", fake_sleep)
    for _ in range(3):
        wait = asyncio.run(op.outbound_backoff("pytest-key", 12, base=1.0))
        assert 0 < wait <= op.CAP_SECONDS * 1.25
    assert len(slept) == 3


def test_data_bus_delivery_backoff_stays_capped():
    text = (SRC / "api" / "databus_bridge.py").read_text()
    assert "outbound_backoff(" in text or re.search(r"min\(\s*2\s*\*\*\s*a\s*,\s*30", text)


def test_llm_stream_retry_uses_canonical_backoff():
    text = (SRC / "intelligence" / "llm" / "base_streaming.py").read_text()
    assert "outbound_backoff(" in text
    assert not re.search(r"2\*\*attempt", text)
