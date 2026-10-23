"""Health-probe logging contract — one line per state change, never a traceback.

Incident 2026-10-23: an unreachable optional Ollama logged a multi-frame
``httpx.ConnectError`` traceback on every ``/health`` call (61 in 10 minutes,
80% of all log bytes), so real scrape failures were invisible. These tests pin
the replacement behaviour: a dead optional dependency costs ONE line, a
steady-state failure costs none, and no probe ever logs ``exc_info``.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.health import router
from pry.api.routers.core.probe_log import ProbeFailure, ProbeLog, ProbeTiming, probes

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def _probe_records(caplog, message: str | None = None, dependency: str | None = None):
    """Probe log lines, optionally narrowed to one message and one dependency."""
    return [
        r
        for r in caplog.records
        if r.getMessage().startswith("health_probe")
        and (message is None or r.getMessage() == message)
        and (dependency is None or getattr(r, "dependency", None) == dependency)
    ]


def _ollama_down(caplog):
    """Every real dependency patched up, the optional LLM client dead."""
    dead = AsyncMock()
    dead.get = AsyncMock(side_effect=httpx.ConnectError("All connection attempts failed"))
    up = AsyncMock(return_value=True)
    return (
        patch("pry.api.routers.core.health._check_redis", up),
        patch("pry.api.routers.core.health._check_database", up),
        patch("pry.api.routers.core.health._check_flaresolverr", up),
        patch("pry.api.routers.core.probe_checks.get_client", AsyncMock(return_value=dead)),
        caplog.at_level(logging.DEBUG, logger="pry.api.routers.core.probe_log"),
    )


def test_dead_optional_dep_logs_one_line_without_traceback(caplog) -> None:
    """Two failed /health calls emit ONE line — the state-change line."""
    probes.reset()
    with ExitStack() as stack:
        for patch_cm in _ollama_down(caplog):
            stack.enter_context(patch_cm)
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200

    failed = _probe_records(caplog, "health_probe_failed", "ollama")
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
            log.report(
                "store",
                ok,
                ProbeTiming(elapsed_ms=3, budget_ms=800),
                ProbeFailure(reason="connect", optional=True),
            )
    finally:
        target.removeHandler(handler)

    assert seen == ["health_probe_failed", "health_probe_recovered"]


def test_steady_failure_is_debug_only(caplog) -> None:
    """A dependency that stays down does not re-log at production levels."""
    log = ProbeLog()
    with caplog.at_level(logging.INFO, logger="pry.api.routers.core.probe_log"):
        log.report(
            "store",
            False,
            ProbeTiming(elapsed_ms=1, budget_ms=800),
            ProbeFailure(reason="connect", optional=True),
        )
        log.report(
            "store",
            False,
            ProbeTiming(elapsed_ms=1, budget_ms=800),
            ProbeFailure(reason="connect", optional=True),
        )
    assert [r.getMessage() for r in _probe_records(caplog)] == ["health_probe_failed"]
