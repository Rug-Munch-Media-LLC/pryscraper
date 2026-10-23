# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""The failure-reason dimension: bounded labels, honest verdicts, real budgets."""

import httpx
import pytest

from pry.core.errors import ScrapeError
from pry.core.scrape_reason import classify_failure
from pry.engine import tiers_http
from pry.engine.scraper_orchestrate import classify_verdict
from pry.engine.tiers_http import TierHTTPMixin


@pytest.mark.parametrize("verdict", ["blocked", "exhausted", "unavailable"])
def test_verdict_passes_through_as_reason(verdict: str) -> None:
    assert classify_failure(ScrapeError("x", verdict=verdict)) == verdict


def test_scrape_error_without_verdict_is_chain_failed() -> None:
    assert classify_failure(ScrapeError("x")) == "chain_failed"
    assert classify_failure(ScrapeError("x", verdict="weird")) == "chain_failed"


def test_transport_errors_map_to_bounded_labels() -> None:
    assert classify_failure(httpx.ReadTimeout("t")) == "timeout"
    assert classify_failure(TimeoutError()) == "timeout"
    assert classify_failure(httpx.ConnectError("c")) == "connect"
    assert classify_failure(httpx.HTTPError("h")) == "http"
    assert classify_failure(RuntimeError("boom")) == "exception"


def test_flaresolverr_timeout_is_not_a_missing_dependency() -> None:
    """75/214 flaresolverr losses were killed at 45 s, not unavailable."""
    assert classify_verdict(["flaresolverr_timeout"], None, 14) == "exhausted"


def test_missing_browser_is_unavailable() -> None:
    err = "Browser version 'chrome' not found. Run `camoufox list`"
    assert classify_verdict([err], None, 14) == "unavailable"


class _FakeStream:
    def __aenter__(self):
        raise ValueError("captured")

    def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, sink: list) -> None:
        self.sink = sink

    def stream(self, method: str, url: str, **kwargs):
        self.sink.append({"method": method, "url": url, **kwargs})
        return _FakeStream()


@pytest.mark.parametrize(("env_s", "expected_ms"), [("45", 40000), ("12", 10000), ("90", 85000)])
async def test_flaresolverr_max_timeout_fits_the_ladder(
    monkeypatch: pytest.MonkeyPatch, env_s: str, expected_ms: int
) -> None:
    """FlareSolverr must answer inside the ladder deadline, never beyond it."""
    from pry.core.settings import settings

    sink: list = []
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", env_s)
    monkeypatch.setattr(settings, "flaresolverr_url", "http://flare/v1", raising=False)
    monkeypatch.setattr(tiers_http, "_get_shared_client", lambda: _fake_client(sink))
    assert await TierHTTPMixin()._tier_flaresolverr("https://example.com", {}) is None
    assert sink[0]["json"]["maxTimeout"] == expected_ms
    # The client gives up one second BEFORE the ladder's kill, so the
    # sidecar's verdict arrives instead of a blind asyncio cancellation.
    assert sink[0]["timeout"] == float(env_s) - 1


async def _fake_client(sink: list) -> _FakeClient:
    return _FakeClient(sink)
