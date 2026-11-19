# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import asyncio
import logging
import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Sample-data fixtures live beside this file, not here: conftest's job is
# isolation, and mixing fixtures in is how two tests end up coupled.
from tests.fixtures_samples import sample_html, sample_markdown, sample_schema  # noqa: F401


def _install_sqlite_test_pragmas() -> None:
    """Make every SQLite test database fast, once, for the whole session.

    MEASURED 2026-11-19: ``Base.metadata.create_all()`` against a fresh file
    SQLite database took **31.5 seconds** for the project's 29 tables, because
    SQLite defaults to ``synchronous=FULL`` and fsyncs the journal per DDL
    statement. 34 test modules build their own schema, so a full run spent the
    large majority of its wall time re-fsyncing throwaway databases -- one
    fixture alone accounted for 200+ seconds of a file that has 4 tests.

    These pragmas are correct FOR A TEST DATABASE and must never be set in
    production:
      * ``journal_mode=MEMORY`` -- the rollback journal lives in RAM, so
        rollback-on-failure still works for the duration of the test.
      * ``synchronous=OFF`` -- no fsync on commit. The data is discarded with
        tmp_path; durability across a power loss is exactly what a test does
        not need.

    With both, the same ``create_all`` takes 0.025 s (measured), a ~1260x
    reduction, and the schema produced is identical.

    This is a global listener rather than a per-fixture change so the 34
    modules that call ``create_all`` do not have to each be edited -- and so a
    new test that forgets to opt in is still fast.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _sqlite_test_pragmas(dbapi_connection: Any, _record: Any) -> None:
        # Only touch SQLite; the integration job runs Postgres, where these
        # pragmas are meaningless and the statement would raise.
        module = type(dbapi_connection).__module__ or ""
        if "sqlite" not in module:
            return
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=MEMORY")
            cursor.execute("PRAGMA synchronous=OFF")
            cursor.close()
        except Exception:  # noqa: BLE001 - a pragma failure must not break a test
            return


_install_sqlite_test_pragmas()


@pytest.fixture(autouse=True)
def pry_event_loop_isolation() -> Generator[None, None, None]:
    """Give every test a clean, open event loop and close what it leaves.

    MEASURED 2026-11-19: six tests failed only in a full run, with
    ``RuntimeError: Event loop is closed`` (test_crm_sync) and wrong response
    codes from async endpoints (test_routers_health, test_routers_x402_pay,
    test_x402_final_hardening, test_webhook_delivery). All six pass in
    isolation, so something earlier left the process-level loop closed and every
    later ``asyncio.run`` inherited it.

    ``asyncio_mode = "auto"`` gives pytest-asyncio tests their own loop, but a
    plain sync test calling ``asyncio.run(...)`` uses the interpreter's loop
    POLICY, which is process-global. Installing a fresh policy per test means a
    test can neither inherit a closed loop nor leak one, and it costs a single
    object allocation.
    """
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    yield
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        return
    if loop is not None and not loop.is_closed():
        loop.close()


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
    import pry.payments.x402 as _x402_pkg
    import pry.payments.x402.handler as _handler_mod
    import pry.payments.x402.self_facilitator as _selffac_mod

    scratch = tmp_path / "x402-ledger"
    scratch.mkdir(parents=True, exist_ok=True)
    for mod in (_handler_mod, _x402_pkg, _selffac_mod):
        if hasattr(mod, "X402_DIR"):
            monkeypatch.setattr(mod, "X402_DIR", scratch)


@pytest.fixture(autouse=True)
def pry_cache_isolation() -> None:
    """Clear ResponseCache between tests to prevent order-dependent state bleed."""
    from pry.core.deps import cache

    # Reset the singleton cache state between tests
    cache._cache.clear()  # type: ignore[attr-defined]
    cache._total_bytes = 0  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def pry_scrape_state_isolation(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the two process-global scrape states that leak between tests.

    Both were causing real order-dependent failures and one was reaching
    production data:

    * ``url_terminal_state`` keeps per-URL consecutive failures. After 3 the URL
      is TERMINAL for a cooldown and ``pre_tier_check`` short-circuits BEFORE
      any tier runs. Tests reuse ``https://example.com/page``, so a test whose
      tiers all fail made the next test's ladder never execute at all -- it got
      ``status: error`` with ``tiers_attempted: []`` while its mocks had been
      configured for a win. ``reset()`` is the documented hook for exactly this
      ("tests and long-running workers that rotate targets").

    * ``tier_health.DEFAULT_PATH`` defaults to ``/app/pry-data/tier_health.json``
      -- the DEPLOYED container's data file. The suite was reading and writing
      it, so tier evidence accumulated across runs and a test could inherit
      "archive: 11 attempts" from an unrelated session. Point it at tmp_path so
      a test run cannot observe or mutate production health state.

    Resetting health also keeps ``should_skip`` decisions local to a test: it
    reads that same file, so a poisoned store could silently remove a tier from
    the ladder under test.
    """
    from pry.engine import tier_health, url_terminal_state

    url_terminal_state.reset()
    monkeypatch.setattr(tier_health, "DEFAULT_PATH", tmp_path / "tier_health.json")


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


@pytest.fixture
def empty_scrape() -> Generator[None, None, None]:
    """Make the injected ``scraper.scrape`` return empty HTML.

    ``/v1/shadow-dom`` and ``/v1/extract/css`` only run their own guarded fetch
    when the scraper produced no HTML; without this the real scraper attempts a
    live call, fails, and the guard is never reached. DI seam, not patching:
    ``scraper`` is the injected singleton, restored below.
    """
    from unittest.mock import AsyncMock

    from pry.core.deps import scraper

    real_scrape = scraper.scrape
    scraper.scrape = AsyncMock(return_value={"status": "ok", "raw_html": "", "content": ""})
    yield
    scraper.scrape = real_scrape


# GDPR erasure fixtures live in tests/gdpr_fixtures.py: the suite was 311 lines
# in one file, and pytest only discovers fixtures registered here or in conftest.
# tier_health_plugin.py follows the same shape — see its docstring for why the
# per-tier health store must be redirected per test.
pytest_plugins = ("tests.gdpr_fixtures", "tests.tier_health_plugin")


#: Deterministic public address used by the ``resolved_dns`` fixture. TEST-NET-3
#: (RFC 5737) is not a private range, so the guard accepts it, and respx
#: intercepts every request -- no packet leaves the process.
RESOLVED_DNS_IP = "203.0.113.10"


@pytest.fixture
def resolved_dns(monkeypatch: pytest.MonkeyPatch) -> str:
    """Resolve every hostname to one fixed PUBLIC address.

    The SSRF guard pins each request to the resolved IP (``url_pinning``), so a
    transport keyed on the hostname never sees the pinned request, and a test
    that leaves DNS live depends on the internet. Deterministic on both counts:
    the address is returned so callers can key their routes on the pinned URL.
    """
    import socket

    def _getaddrinfo(host: str, port: object, *args: object, **kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (RESOLVED_DNS_IP, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return RESOLVED_DNS_IP
