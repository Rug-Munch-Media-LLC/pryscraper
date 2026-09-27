# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""GET /metrics — the degraded stub must not report a healthy facilitator.

The handler is invoked directly rather than over HTTP: ``wire_app()`` calls
``register_routers()``, which registers ``routers/core/system.py``'s
``/metrics`` before this module's decorator runs, so Starlette resolves the
earlier route. See [REVIEW] in the commit body — that shadowing is separate
from the fabricated gauge this test covers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import prometheus_client
from fastapi.testclient import TestClient

from pry.api.app_factory import METRICS_STUB_MARKER, app, get_metrics

if TYPE_CHECKING:
    import pytest

    MonkeyPatch = pytest.MonkeyPatch

client = TestClient(app)


def _registry_unavailable() -> str:
    raise RuntimeError("registry unavailable")


def test_metrics_stub_reports_unhealthy_and_marks_degradation(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    """Registry absent → gauge 0, stub marker present, and the event logged.

    A fabricated ``x402_facilitator_healthy 1`` on an unreachable registry is a
    green gauge on a broken system: every alert keyed on that gauge stays
    silent while the facilitator is actually down.
    """
    monkeypatch.setattr(prometheus_client, "generate_latest", _registry_unavailable)

    with caplog.at_level(logging.WARNING, logger="pry.api.app_factory"):
        body = asyncio.run(get_metrics())

    # The gauge must read 0, not 1.
    assert "x402_facilitator_healthy 0" in body
    assert "x402_facilitator_healthy 1" not in body

    # A distinct marker so a scraper can tell stub from real registry data.
    assert f"{METRICS_STUB_MARKER} 1" in body
    assert f"# TYPE {METRICS_STUB_MARKER} gauge" in body

    # The operator signal that the real registry is gone.
    assert "metrics_stub_served" in caplog.text

    # The x402 fallbacks the stub has always carried are unchanged.
    for sample in (
        "x402_verify_total 0",
        "x402_settle_total 0",
        "x402_verify_failures_total 0",
    ):
        assert sample in body

    # The real path is untouched: registry restored → no stub, real HELP lines.
    monkeypatch.undo()
    live = asyncio.run(get_metrics())
    assert f"{METRICS_STUB_MARKER} 1" not in live
    assert "# HELP" in live
