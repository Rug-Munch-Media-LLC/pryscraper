"""Dark-path coverage for the ASGI response paths of src/pry/core/middleware.py.

Sibling of :mod:`tests.test_middleware_dark_paths` (audit win B9), which holds
the auth-helper, usage-flush and route-table evidence. This file is the
end-to-end half: the request actually reaches the middleware and the middleware
answers, rather than being exercised helper by helper.

The blocked-rate-limit path is the one that matters most here. A limiter
refusal must produce a 429 carrying ``retry_after`` and the rate-limit headers
over a well-formed JSON error body -- and must never reach the downstream app.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from pry.core import middleware as mw
from pry.core.middleware import PryHttpMiddleware


def test_rate_limit_blocked_emits_429_with_headers() -> None:
    """When the limiter refuses, the middleware answers 429 + retry_after."""
    stats = {
        "limit": 5,
        "remaining": 0,
        "quota_reset_at": 9999999999,
        "quota_used": 5,
        "quota_limit": 10000,
        "retry_after": 3,
        "reason": "rate_limited",
    }
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("downstream must not see blocked requests")

    # Route table must know the path, else the unknown-path pass-through
    # returns before rate limiting ever runs. Must be REAL Starlette
    # routes — the matcher isinstance-checks them.
    from starlette.routing import Route

    async def _endpoint():  # pragma: no cover - never invoked
        return {}

    app.routes = [Route("/v1/scrape", _endpoint)]
    mw_inst = PryHttpMiddleware(app=app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [(b"authorization", b"Bearer dbkey1234567890")],
        "client": ("203.0.113.9", 5),
        "query_string": b"",
    }
    with (
        patch.object(mw, "request_authorized", return_value=True),
        # autospec so the awaited refresh_quota() is an AsyncMock — a bare
        # MagicMock cannot be awaited, and the request path awaits it before
        # check() to keep the fail-closed quota gate reachable.
        patch.object(mw, "user_ratelimiter", autospec=True) as rl,
    ):
        rl.check.return_value = (False, stats)
        asyncio.run(mw_inst.__call__(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 429
    hdrs = dict(sent[0]["headers"])
    assert hdrs[b"x-ratelimit-remaining"] == b"0"
    assert hdrs[b"x-request-id"]
    body = json.loads(sent[1]["body"])
    assert body["code"] == "rate_limit_exceeded"
