# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_html() -> str:
    return """<!DOCTYPE html><html><head><title>Test Page</title>
<meta name="description" content="A test page for scraping">
</head><body>
<h1 class="product-title">Widget Pro</h1>
<p class="price">$29.99</p>
<p class="description">The best widget ever made.</p>
<a href="https://example.com/page1">Page 1</a>
<a href="https://example.com/page2">Page 2</a>
<a href="https://external.com">External</a>
</body></html>"""


@pytest.fixture
def sample_markdown() -> str:
    return """# Widget Pro

**Price:** $29.99

The best widget ever made.

- Feature 1: Lightweight
- Feature 2: Durable
- Feature 3: Affordable

Contact: sales@example.com
"""


@pytest.fixture
def sample_schema() -> dict:
    return {
        "product_name": "name of the product",
        "price": "price in USD",
        "email": "contact email email",
    }


# ── Lenient LogRecord for tests ─────────────────────────────────
# Some Pry modules (and tests) use logger.warning("...", extra={"name": "foo"})
# patterns. Python's stdlib logging rejects this with KeyError because
# "name" is a reserved LogRecord field. In tests we make the LogRecord
# tolerant: reserved keys in `extra` are moved to a sub-dict so the call
# doesn't crash. This matches the behavior we get with structlog's bridge.
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

    os.environ["PRY_SECRET_BACKEND"] = "env"  # noqa: S105
    os.environ.setdefault("PRY_API_KEY", "")
    os.environ.setdefault("PRY_OPENROUTER_API_KEY", "")
    os.environ.setdefault("PRY_OPENAI_API_KEY", "")
    os.environ.setdefault("PRY_ANTHROPIC_API_KEY", "")
    os.environ.setdefault("PRY_COHERE_API_KEY", "")


@pytest.fixture(autouse=True)
def pry_test_auth(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    import settings as _settings_mod

    original = _settings_mod.settings.api_key
    _settings_mod.settings.api_key = ""
    yield
    _settings_mod.settings.api_key = original


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    from fastapi.testclient import TestClient

    from api import app

    with TestClient(app) as c:
        yield c
