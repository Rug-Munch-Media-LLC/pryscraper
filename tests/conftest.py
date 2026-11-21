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

_log = logging.getLogger(__name__)


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
    test can neither inherit a closed loop nor leak one.

    Setting the policy alone is NOT enough: on a fresh policy ``get_event_loop()``
    still hands back a CLOSED loop in some pytest states, and callers that build a
    coroutine and hand it to ``asyncio.wait_for`` (the health probes do exactly
    this via ``bounded()``) then get a failed probe instead of a result. MEASURED
    2026-11-20: ``/ready`` reported ``{"database": True, "redis": False}`` in a
    full run because the probe coroutine never ran on the closed loop -- the last
    two failing tests in the suite, and the reason they passed alone. So an OPEN
    loop is installed explicitly, not just a new policy.
    """
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    # Close the loop this fixture opened so it cannot leak into the next test,
    # and detach it from the policy first so no later caller can retrieve it.
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)


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
def pry_test_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank the API key for every test, and restore it via monkeypatch.

    The previous version saved ``original = settings.api_key`` and assigned it
    back by hand in teardown. That lost to monkeypatch: a test that does
    ``monkeypatch.setattr(settings, "api_key", ...)`` patches the value AFTER
    this fixture already ran, and its own restore writes back whatever was
    there when IT patched -- which was this fixture's blanked "". Whichever
    teardown ran last won, so a run could end with a random per-run master key
    left in a process-global settings singleton. That is exactly what the
    global-watch run reported::

        SETTINGS LEAK test_admin_authz.py::...: {'api_key': (<random>, '')}

    Using ``monkeypatch.setattr`` here instead makes pytest own the save and
    restore, so the ordering is deterministic: every patch is undone in reverse
    order of application, and the real original always comes back.

    ``settings`` is a module-level singleton built once at import, so it can
    only be restored by patching an attribute -- not by rebuilding it, which
    would break every module holding a reference.
    """
    import pry.core.settings as _settings_mod

    monkeypatch.setattr(_settings_mod.settings, "api_key", "", raising=False)
    # No teardown body: pytest undoes the patch itself, in reverse order.


@pytest.fixture(autouse=True)
def pry_scheduler_lock_isolation() -> Generator[None, None, None]:
    """Clear the in-process monitor claim table between tests.

    ``scheduler._LOCAL`` is a process-global ``{monitor_id: expiry}`` dict with a
    default TTL of 900 seconds, and ``claim_monitor`` returns "already held"
    for anything still inside that window. Nothing cleared it between tests, so
    once one test claimed a monitor id, every later test using the same id saw
    its ``scrape`` skipped and got zero runs.

    MEASURED 2026-11-20: this is why ``test_monitor_scheduler`` passed alone and
    failed under xdist -- the two callers in a single test are sequential in one
    process, but a *previous file on the same worker* had already left the claim
    in place. Serial full runs happened to order the files open, which is why
    the failure only appeared with parallelism.

    A test that asserts the claim behaviour still works: it claims and checks
    within its own body, starting from an empty table.
    """
    from pry.actors import scheduler as _sched

    with _sched._LOCAL_LOCK:
        _sched._LOCAL.clear()
    yield
    with _sched._LOCAL_LOCK:
        _sched._LOCAL.clear()


@pytest.fixture(autouse=True)
def pry_facilitator_isolation() -> Generator[None, None, None]:
    """Restore the global facilitator router after every test.

    MEASURED 2026-11-20: ``set_facilitator_router()`` replaces a MODULE-GLOBAL
    (``pry.payments.x402.facilitator._facilitator_router``) and nothing put it
    back. ``tests/test_pry_regression.py`` installs a ``TestRouter`` whose
    ``verify()`` returns ``verified: True`` unconditionally, so once that file
    had run, the whole process was using a router that approves every payment
    AND reports ``ready: False`` from ``readiness()``.

    That single leak caused all four of the remaining full-run failures:

      * /ready and /health returned 503 (the fake router is never ready)
      * the underpayment test got ``success: True`` for a 0.001 payment
      * the attestation-signature test got 200 instead of 402

    Restoring the previous router object here makes the leak impossible no
    matter which test stubs it, rather than patching one file and waiting for
    the next to do the same thing.
    """
    from pry.payments.x402 import facilitator as _fac

    previous = _fac._facilitator_router
    yield
    _fac._facilitator_router = previous


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


@pytest.fixture(autouse=True)
def pry_database_isolation(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point EVERY test at its own SQLite file, never the live database.

    MEASURED 2026-11-20: with no default isolation, a full run left the engine
    at ``sqlite:////root/.pry/pry.db`` -- the DEPLOYED service's database, 4.2 MB
    of real rows. Tests were reading and writing production state: the
    /health suite reported a live DB while asserting a mocked one, and four
    tests failed only in a full run because they inherited rows another test
    had written.

    ``temp_data_dir`` already did this correctly but was OPT-IN, so 34 test
    modules either reinvented it (billing_support, hosting_support) or forgot.
    Making it autouse means a new test cannot accidentally touch the real
    database, and the opt-in fixture below still exists for files that want to
    assert against the returned path.

    The engine globals are reset before AND after so a disposed or
    differently-bound engine from a previous test cannot leak in, and the URL is
    set through monkeypatch so the real environment is restored at teardown.
    """
    db_path = tmp_path / "pry-test.db"
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{db_path}")

    import pry.core.db as db
    import pry.core.db.db_engine as db_engine_mod

    def _reset() -> None:
        for mod in (db, db_engine_mod):
            for attr in ("_engine", "_SessionLocal", "_async_engine", "_async_session_local"):
                if hasattr(mod, attr):
                    setattr(mod, attr, None)

    _reset()
    # Create the schema in the fresh database. Some tests relied on the live
    # database already having tables (they got "no such table: users" once the
    # real file was no longer in play), and a test must never depend on
    # production rows to exist. `init_db()` is the documented cold-start/test
    # helper; it honours PRY_ALEMBIC_AUTO.
    try:
        from pry.core.db.db_init import init_db

        init_db()
    except Exception:  # noqa: BLE001 - a schema setup failure must surface as a test failure, not a fixture crash
        _log.debug("pry_database_isolation_init_failed", exc_info=True)
    # NO teardown: this fixture's setup calls _reset() before every test, so a
    # stale engine can never be inherited. A teardown WOULD be harmful -- it runs
    # in reverse fixture order and fired while a module-level fixture like
    # `test_monitor_scheduler.temp_db` was still tearing down, clearing the engine
    # it still needed (three monitor tests failed 'assert 0 == 1'). `return`, not
    # `yield`, so ruff's PT022 does not read this as a missing teardown body. It is unnecessary -- this fixture's own setup calls
    # _reset() before every test, so a stale engine can never be inherited -- and
    # it is HARMFUL: teardown runs in reverse fixture order, so this fired while
    # a module-level fixture like `test_monitor_scheduler.temp_db` was still
    # tearing down and needed the engine IT built. That cleared `_engine` under
    # it and produced `assert 0 == 1` ("scrape never happened") in three monitor
    # tests that had passed for months.


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine.

    Hoisted here so every DB-touching test file gets the SAME isolation.
    It was previously copy-pasted per file, which is how a suite ends up with
    two tests pointing at two different databases and blaming each other.

    ``pry_database_isolation`` (autouse) already does the environment part; this
    fixture remains for tests that need the PATH back, and re-asserts the env so
    a caller get explicit control.
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
