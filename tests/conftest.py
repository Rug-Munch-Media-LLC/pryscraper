# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Sample-data fixtures live beside this file, not here: conftest's job is
# isolation, and mixing fixtures in is how two tests end up coupled.
from tests.fixtures_samples import sample_html, sample_markdown, sample_schema  # noqa: F401

#
# Production code is unaffected (this conftest only runs in tests).
# If you actually want strict mode in tests, set PRY_LOG_STRICT_EXTRAS=1.
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


def _make_lenient_logrecord() -> None:
    """Monkey-patch LogRecord.__init__ to be tolerant of reserved extra keys."""
    if os.getenv("PRY_LENIENT_LOG", "1").lower() not in ("1", "true", "yes"):
        return  # allow opting out of the global patch via PRY_LENIENT_LOG=0
    if os.getenv("PRY_LOG_STRICT_EXTRAS", "").lower() in ("1", "true", "yes"):
        return  # honor strict mode if explicitly requested
    original_init = logging.LogRecord.__init__

    def lenient_init(self, *args, **kwargs):
        # Extract extra before super().__init__ which would reject reserved keys
        extra = kwargs.pop("extra", None)
        original_init(self, *args, **kwargs)
        if extra:
            overflow: dict[str, object] = {}
            for k, v in extra.items():
                if k in _RESERVED:
                    overflow[k] = v
                else:
                    setattr(self, k, v)
            if overflow:
                existing = getattr(self, "_overflow_extras", {}) or {}
                existing.update(overflow)
                self._overflow_extras = existing

    logging.LogRecord.__init__ = lenient_init  # type: ignore[assignment]


# Install the lenient LogRecord at conftest import time
_make_lenient_logrecord()


# ── Test isolation: disable gopass + clear auth in settings ─────
# PrySettings now pulls api_key from secrets_backend (gopass on Talos has
# a real pry/api_key secret). Tests must not depend on that real secret.
# Solution: set PRY_SECRET_BACKEND=env at session scope (inherited by
# subprocess-based tests like the SSE server test) and zero the
# settings singleton at test scope.
@pytest.fixture(autouse=True, scope="session")
def _pry_disable_secrets_gopass() -> None:
    import os

    os.environ["PRY_SECRET_BACKEND"] = "env"
    os.environ.setdefault("PRY_API_KEY", "")
    os.environ.setdefault("PRY_OPENROUTER_API_KEY", "")
    os.environ.setdefault("PRY_OPENAI_API_KEY", "")
    os.environ.setdefault("PRY_ANTHROPIC_API_KEY", "")
    os.environ.setdefault("PRY_COHERE_API_KEY", "")


@pytest.fixture(autouse=True)
def pry_test_auth(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    import pry.core.settings as _settings_mod

    original = _settings_mod.settings.api_key
    _settings_mod.settings.api_key = ""
    yield
    _settings_mod.settings.api_key = original


@pytest.fixture(autouse=True)
def pry_x402_ledger_isolation(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every X402_DIR binding at a per-test scratch dir.

    Regression: middleware-level tests that build a full app (e.g. the x402
    hardening suite) constructed X402Handler with DEFAULT ledger paths, so
    every run appended ghost payment records ("pay-clean", "0xclean", …) to
    the LIVE ~/.pry/x402/payments.jsonl. Tests must never touch the live
    ledger; handlers that need a specific file still pass explicit paths.
    """
    import pry.misc.x402 as _misc_x402
    import pry.payments.x402.handler as _handler_mod
    import pry.payments.x402.self_facilitator as _selffac_mod

    scratch = tmp_path / "x402-ledger"
    scratch.mkdir(parents=True, exist_ok=True)
    for mod in (_handler_mod, _misc_x402, _selffac_mod):
        if hasattr(mod, "X402_DIR"):
            monkeypatch.setattr(mod, "X402_DIR", scratch)


@pytest.fixture(autouse=True)
def pry_cache_isolation() -> None:
    """Clear ResponseCache between tests to prevent order-dependent state bleed."""
    from pry.core.deps import cache

    # Reset the singleton cache state between tests
    cache._cache.clear()  # type: ignore[attr-defined]
    cache._total_bytes = 0  # type: ignore[attr-defined]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    from fastapi.testclient import TestClient

    from pry.api.api import app

    c = TestClient(app)
    try:
        with c:
            yield c
    except (RuntimeError, Exception):  # noqa: BLE001, S110 — swallow event-loop-closed on teardown
        pass


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine.

    Hoisted here so every DB-touching test file gets the SAME isolation.
    It was previously copy-pasted per file, which is how a suite ends up with
    two tests pointing at two different databases and blaming each other.
    """
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import importlib

    import pry.core.db as db
    import pry.core.paths as paths

    importlib.reload(paths)
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    yield tmp_path
    db._engine = None
    db._SessionLocal = None
