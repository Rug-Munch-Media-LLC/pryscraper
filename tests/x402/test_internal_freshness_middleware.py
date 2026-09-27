"""Replay-protection cover for the internal free path — freshness + cache half.

Regression guard for the 2026-09-27 gap: the internal credential was a bare
HMAC over ``METHOD\\npath\\ncaller``, so one captured request stayed valid for
that endpoint forever. It now also carries a signed ``X-Internal-Timestamp``
checked against ``PRY_INTERNAL_MAX_SKEW_SECONDS`` (default 300) plus a
TTL-evicting seen-signature cache.

Also the shared scaffolding for ``test_internal_replay_middleware.py`` (the
skew + binding half) and a sibling of ``test_internal_gate_middleware.py``
(gate-level cover that predates the timestamp header).
"""

import json
import time

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware
from pry.payments.x402_middleware.internal import (
    _SEEN_SIGNATURES,
    INTERNAL_SIG_HEADER,
    INTERNAL_TIMESTAMP_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_signature,
)

TOKEN = "internal-secret"
PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.7"


class _StubApp:
    """Minimal ASGI app that records whether it was reached."""

    def __init__(self) -> None:
        """Track invocation for assertions."""
        self.called = False

    async def __call__(self, scope: dict, receive, send) -> None:
        """ASGI entry point: mark reached and return a 200."""
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": PAID_PATH,
        "headers": headers,
        "query_string": b"",
        "client": (CALLER, 51000),
    }


def _headers(timestamp: str, signature: str | None = None) -> list[tuple[bytes, bytes]]:
    """Internal headers carrying ``timestamp``; signature defaults to the real HMAC."""
    sig = signature or internal_signature(TOKEN, "POST", PAID_PATH, CALLER, timestamp)
    return [
        (INTERNAL_TOKEN_HEADER, TOKEN.encode()),
        (INTERNAL_SIG_HEADER, sig.encode()),
        (INTERNAL_TIMESTAMP_HEADER, timestamp.encode()),
    ]


def _now(offset: int = 0) -> str:
    return str(int(time.time()) + offset)


async def _call(app: _StubApp, headers: list[tuple[bytes, bytes]]) -> list[dict]:
    scope = _scope(headers)
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await X402Middleware(app, wallet="0x0", network="base")(scope, receive, send)
    return sent


def _assert_challenged(app: _StubApp, sent: list[dict]) -> None:
    assert not app.called, "request must not reach the app"
    assert sent, "a challenge response must be sent"
    assert sent[0]["status"] == 402
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert body, "402 response carries the payment challenge body"
    assert json.loads(body.decode() or "{}")


def _assert_served(app: _StubApp, sent: list[dict]) -> None:
    assert app.called, "internal request must reach the app"
    assert sent[0]["status"] == 200


def _configure(monkeypatch: pytest.MonkeyPatch, skew: str | None = None) -> None:
    """Set the internal token and (optionally) the max-skew setting."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    if skew is None:
        monkeypatch.delenv("PRY_INTERNAL_MAX_SKEW_SECONDS", raising=False)
    else:
        monkeypatch.setenv("PRY_INTERNAL_MAX_SKEW_SECONDS", skew)
    # The signed caller is the trusted-proxy-resolved client IP, so pin the
    # proxy list: an ambient PRY_TRUSTED_PROXIES would move the bound key.
    monkeypatch.setenv("PRY_TRUSTED_PROXIES", "")


# ── Freshness window ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_timestamp_reaches_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """A correctly stamped, current credential still gets the free path."""
    _configure(monkeypatch)
    app = _StubApp()
    _assert_served(app, await _call(app, _headers(_now())))


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-3600, 3600])
async def test_stale_timestamp_is_challenged(monkeypatch: pytest.MonkeyPatch, offset: int) -> None:
    """Outside the 300s default window, in either direction, must 402."""
    _configure(monkeypatch)
    app = _StubApp()
    _assert_challenged(app, await _call(app, _headers(_now(offset))))


@pytest.mark.asyncio
async def test_missing_timestamp_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid token + signature with no timestamp is rejected (fail closed)."""
    _configure(monkeypatch)
    app = _StubApp()
    sig = internal_signature(TOKEN, "POST", PAID_PATH, CALLER, _now())
    sent = await _call(
        app, [(INTERNAL_TOKEN_HEADER, TOKEN.encode()), (INTERNAL_SIG_HEADER, sig.encode())]
    )
    _assert_challenged(app, sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [b"not-a-number", b"", b"12.5", b"-1", b"1e9"])
async def test_non_numeric_timestamp_is_challenged(
    monkeypatch: pytest.MonkeyPatch, bad: bytes
) -> None:
    """Only a plain non-negative integer is a timestamp; everything else 402s."""
    _configure(monkeypatch)
    app = _StubApp()
    sent = await _call(
        app,
        [
            (INTERNAL_TOKEN_HEADER, TOKEN.encode()),
            (INTERNAL_SIG_HEADER, b"irrelevant"),
            (INTERNAL_TIMESTAMP_HEADER, bad),
        ],
    )
    _assert_challenged(app, sent)


# ── Replay cache ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replayed_signature_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same captured request is served once; a second use must 402."""
    _configure(monkeypatch)
    headers = _headers(_now())
    first = _StubApp()
    _assert_served(first, await _call(first, headers))
    second = _StubApp()
    _assert_challenged(second, await _call(second, headers))


@pytest.mark.asyncio
async def test_cache_entry_is_evicted_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signature is remembered only while it could still be inside the window."""
    _configure(monkeypatch)
    headers = _headers(_now())
    await _call(_StubApp(), headers)
    assert len(_SEEN_SIGNATURES) == 1
    for seen in list(_SEEN_SIGNATURES):
        _SEEN_SIGNATURES[seen] -= 10_000  # expire the entry
    app = _StubApp()
    _assert_served(app, await _call(app, headers))
