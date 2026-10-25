# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Dataset-push retry policy: transient retry, exhaustion, and fail-fast.

The sleep function is injected, so backoff is asserted on its recorded waits
instead of by actually sleeping.
"""

from __future__ import annotations

from typing import Any

import pytest

from pry.actors.apify_actor import ApifyActorOutput
from pry.actors.apify_actor.push import _push_with_retry


class RecordingActor:
    """Push target that fails the first ``failures`` calls, then succeeds."""

    def __init__(self, failures: int = 0, error: Exception | None = None) -> None:
        self.failures = failures
        self.error = error or OSError("connection reset")
        self.pushes: list[dict[str, Any]] = []

    async def push_data(self, item: dict[str, Any]) -> None:
        if self.failures:
            self.failures -= 1
            raise self.error
        self.pushes.append(item)


class RecordingSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def item() -> ApifyActorOutput:
    return ApifyActorOutput(url="https://e.com", status="ok", scraped_at="2026-10-25")


class TestPushRetry:
    async def test_success_on_first_attempt_pushes_once_and_never_sleeps(self) -> None:
        actor, sleep = RecordingActor(), RecordingSleep()
        await _push_with_retry(actor, item(), sleep=sleep)

        assert len(actor.pushes) == 1
        assert sleep.waits == []

    async def test_transient_failure_retries_then_succeeds(self) -> None:
        actor, sleep = RecordingActor(failures=2), RecordingSleep()
        await _push_with_retry(actor, item(), sleep=sleep)

        assert len(actor.pushes) == 1
        assert sleep.waits == [1, 2]  # exponential, one wait between attempts

    async def test_backoff_is_capped(self) -> None:
        actor, sleep = RecordingActor(failures=4), RecordingSleep()
        await _push_with_retry(actor, item(), max_retries=5, sleep=sleep)
        assert sleep.waits == [1, 2, 4, 8]

    async def test_exhaustion_logs_error_and_returns_without_raising(self, caplog) -> None:
        actor, sleep = RecordingActor(failures=3), RecordingSleep()
        with caplog.at_level("ERROR", logger="pry.actors.apify_actor.push"):
            await _push_with_retry(actor, item(), sleep=sleep)

        assert actor.pushes == []
        assert sleep.waits == [1, 2]
        assert "apify_push_failed" in caplog.text

    async def test_max_retries_one_is_a_single_attempt(self) -> None:
        actor, sleep = RecordingActor(failures=1), RecordingSleep()
        await _push_with_retry(actor, item(), max_retries=1, sleep=sleep)

        assert actor.pushes == []
        assert sleep.waits == []

    async def test_non_transient_error_propagates(self) -> None:
        """Typed handling: a programming error is not retried or swallowed."""
        actor = RecordingActor(failures=1, error=ValueError("bad payload"))
        with pytest.raises(ValueError, match="bad payload"):
            await _push_with_retry(actor, item(), sleep=RecordingSleep())
