"""Shared scaffolding for the ladder backtest tests.

Extracted so both test files can stay under the 200-line cap. Pure: builds
synthetic probe results, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _ok(url: str, ms: float = 5.0, via: str = "direct") -> dict[str, Any]:
    return {"url": url, "expect": "ok", "note": "", "result": "ok", "latency_ms": ms, "via": via}


def _fail(url: str, ms: float = 5.0) -> dict[str, Any]:
    return {
        "url": url,
        "expect": "ok",
        "note": "",
        "result": "fail",
        "latency_ms": ms,
        "detail": "x",
    }


def _dead(url: str) -> dict[str, Any]:
    """A probe result where Pry was never reached."""
    return {
        "url": url,
        "result": "unavailable",
        "latency_ms": 0.0,
        "detail": "ConnectError",
    }


class FakeClient:
    """Stands in for httpx.AsyncClient. Never opens a socket."""

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def stub_probe(monkeypatch: pytest.MonkeyPatch):
    """Replace the only network function and record the order it was called in."""

    def _install(script: list[tuple[str, Any]]):
        calls: list[str] = []

        async def _probe(client: Any, src: dict[str, Any], pry_timeout: int) -> dict[str, Any]:
            calls.append(src["url"])
            if script:
                return script.pop(0)
            return _ok(src["url"])

        import ladder_backtest as net

        monkeypatch.setattr(net, "probe", _probe)
        return calls

    return _install


# ── the median ────────────────────────────────────────────────────────────
