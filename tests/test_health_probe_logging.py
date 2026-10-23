"""Health-probe logging contract — one line per state change, never a traceback.

Incident 2026-10-23: an unreachable optional Ollama logged a multi-frame
``httpx.ConnectError`` traceback on every ``/health`` call (61 in 10 minutes,
80% of all log bytes), so real scrape failures were invisible. These tests pin
the replacement behaviour: a dead optional dependency costs ONE line, a
steady-state failure costs none, and no probe ever logs ``exc_info``.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.health import router
from pry.api.routers.core.probe_log import ProbeLog, probes

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def _probe_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("health_probe")]


def test_dead_optional_dep_logs_one_line_without_traceback(caplog) -> None:
    """Two failed /health calls emit ONE line — the state-change line."""
    probes.reset()
    dead = AsyncMock()
    dead.get = AsyncMock(side_effect=httpx.ConnectError("All connection attempts failed"))
    up = AsyncMock(return_value=True)

    with (
        patch("pry.api.routers.core.health._check_redis", up),
        patch("pry.api.routers.core.health._check_database", up),
        patch("pry.api.routers.core.health._check_flaresolverr", up),
        patch("pry.api.routers.core.probe_checks.get_client", AsyncMock(return_value=dead)),
        caplog.at_level(logging.DEBUG, logger="pry.api.routers.core.probe_log"),
    ):
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200

    failed = [
        r
        for r in _probe_records(caplog)
        if r.getMessage() == "health_probe_failed" and getattr(r, "dependency", None) == "ollama"
    ]
    assert len(failed) == 1, f"expected one line, got {[r.getMessage() for r in failed]}"
    record = failed[0]
    assert record.optional is True
    assert record.error_type == "ConnectError"
    assert record.exc_info is None, "a probe failure must not carry a traceback"
    assert "Traceback" not in caplog.text


def test_recovery_is_reported_once() -> None:
    """down -> up logs one recovery line, in order, and clears the state."""
    log = ProbeLog()
    seen: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    target = logging.getLogger("pry.api.routers.core.probe_log")
    handler = _Capture()
    target.addHandler(handler)
    # Production level: the repeat warning must be filtered out.
    target.setLevel(logging.INFO)
    try:
        for ok in (False, False, True, True):
            log.report("store", ok, elapsed_ms=3, budget_ms=800, optional=True, reason="connect")
    finally:
        target.removeHandler(handler)

    assert seen == ["health_probe_failed", "health_probe_recovered"]


def test_steady_failure_is_debug_only(caplog) -> None:
    """A dependency that stays down does not re-log at production levels."""
    log = ProbeLog()
    with caplog.at_level(logging.INFO, logger="pry.api.routers.core.probe_log"):
        log.report("store", False, elapsed_ms=1, budget_ms=800, optional=True, reason="connect")
        log.report("store", False, elapsed_ms=1, budget_ms=800, optional=True, reason="connect")
    assert [r.getMessage() for r in _probe_records(caplog)] == ["health_probe_failed"]
