"""Parity proof: the canonical retry delay and rugbrain's retry agree.

Runs the real modules (loaded from the sibling checkout) rather than a copy of
the formula, so the test breaks the day either implementation drifts.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest


def _resolve_root() -> Path | None:
    """Locate the checkout that holds BOTH pryscraper and rugbrain.

    The parity proof compares against rugbrain's REAL retry implementation, so
    it needs a tree where both repos sit side by side. That tree is a sibling
    layout, not a fixed path: this used to default to
    ``/srv/work/wt/xdup45``, one operator's scratch directory, so the whole
    module failed with ``FileNotFoundError`` everywhere else -- a red test that
    said nothing about the code.

    Resolution order, first hit wins:
      1. ``XDUP_ROOT`` — explicit override, kept for a deliberate comparison
         against a specific checkout.
      2. the parent of this repo, when ``<parent>/rugbrain`` also exists
         (the ``/srv/work/repos`` layout).
    Returns None when neither applies; callers skip with that reason rather
    than failing, because "rugbrain is not checked out here" is a fact about
    the machine, not a defect in pry.
    """
    env = os.environ.get("XDUP_ROOT")
    if env:
        p = Path(env)
        return p if (p / "rugbrain").is_dir() else None
    parent = Path(__file__).resolve().parents[2]
    if (parent / "rugbrain").is_dir():
        return parent
    return None


ROOT = _resolve_root()
pytestmark = pytest.mark.skipif(
    ROOT is None,
    reason="needs a checkout holding both pryscraper and rugbrain (set XDUP_ROOT)",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ref():
    return _load("_pry_retry_after", ROOT / "pryscraper/src/pry/engine/retry_after.py")


@pytest.fixture(scope="module")
def rb():
    return _load("_rb_retry", ROOT / "rugbrain/src/rugbrain/ingest_sources/shared/retry.py")


class _Resp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class _Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    async def get(self, url, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _run(monkeypatch, module, client):
    slept: list[float] = []

    async def fake_sleep(delay, *args, **kwargs):
        slept.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    response = asyncio.run(module.get(client, "http://example.test"))
    return response, slept


@pytest.mark.parametrize(
    ("attempt", "header", "expected"),
    [
        (0, None, 0.5),
        (1, None, 1.0),
        (0, "2", 2.0),
        (2, "0.1", 0.1),
        (0, "banana", 0.5),
        (3, "9999", 30.0),
    ],
)
def test_reference_delay_table(ref, attempt, header, expected):
    assert ref.retry_delay(attempt=attempt, base=0.5, header=header) == pytest.approx(expected)


@pytest.mark.parametrize("header", [None, "2", "banana"])
def test_rugbrain_matches_reference(ref, rb, monkeypatch, header):
    expected = ref.retry_delay(attempt=0, base=0.5, header=header)
    client = _Client(_Resp(429, {"Retry-After": header} if header else {}), _Resp(200))
    response, slept = _run(monkeypatch, rb, client)
    assert response.status_code == 200
    assert slept == [pytest.approx(expected)]


def test_retry_after_wins_over_exponential(ref, rb, monkeypatch):
    legacy = 0.5 * (2**0)
    honoured = ref.retry_delay(attempt=0, base=0.5, header="2")
    assert honoured == pytest.approx(2.0)
    assert legacy != honoured
    client = _Client(_Resp(429, {"Retry-After": "2"}), _Resp(200))
    _, slept = _run(monkeypatch, rb, client)
    assert slept == [pytest.approx(2.0)]


def test_success_never_sleeps(rb, monkeypatch):
    client = _Client(_Resp(200))
    response, slept = _run(monkeypatch, rb, client)
    assert response.status_code == 200
    assert slept == []
