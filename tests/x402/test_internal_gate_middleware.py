"""Gate-level cover for the first-party (internal) free path.

Policy under test: external callers stay x402-paid; our own services present
``X-Internal-Token`` + a bound HMAC and are served free. The credential is
fail-closed — an unset ``PRY_INTERNAL_TOKEN`` must NOT make everyone internal.
"""

import json

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware
from pry.payments.x402_middleware.internal import (
    INTERNAL_SIG_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_request,
    internal_signature,
)

TOKEN = "internal-secret"


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


PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.7"


def _scope(headers: list[tuple[bytes, bytes]], path: str = PAID_PATH) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": (CALLER, 51000),
    }


def _internal_headers(method: str = "POST", path: str = PAID_PATH) -> list[tuple[bytes, bytes]]:
    sig = internal_signature(TOKEN, method, path, CALLER)
    return [
        (INTERNAL_TOKEN_HEADER, TOKEN.encode()),
        (INTERNAL_SIG_HEADER, sig.encode()),
    ]


async def _call(middleware: X402Middleware, scope: dict) -> list[dict]:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _assert_challenged(app: _StubApp, sent: list[dict]) -> None:
    assert not app.called, "request must not reach the app without payment"
    assert sent, "a challenge response must be sent"
    assert sent[0]["status"] == 402
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert body, "402 response carries the payment challenge body"
    assert json.loads(body.decode() or "{}")


# ── Gate behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_token_reaches_app_without_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid first-party token + HMAC bypasses the payment gate."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    app = _StubApp()
    scope = _scope(_internal_headers())
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "internal request must reach the app"
    assert sent[0]["status"] == 200
    assert scope.get("x402_verified", {}).get("payment_id") == "internal"


@pytest.mark.asyncio
async def test_missing_internal_signature_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token alone is not enough — the bound HMAC is required."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    app = _StubApp()
    scope = _scope([(INTERNAL_TOKEN_HEADER, TOKEN.encode())])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    _assert_challenged(app, sent)


@pytest.mark.asyncio
async def test_wrong_internal_token_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong token with a well-formed signature must not get the free path."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    app = _StubApp()
    sig = internal_signature("attacker-token", "POST", PAID_PATH, CALLER)
    scope = _scope(
        [
            (INTERNAL_TOKEN_HEADER, b"attacker-token"),
            (INTERNAL_SIG_HEADER, sig.encode()),
        ]
    )
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    _assert_challenged(app, sent)


@pytest.mark.asyncio
async def test_signature_bound_to_another_path_is_challenged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A signature harvested for one endpoint is not replayable on another."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    app = _StubApp()
    scope = _scope(_internal_headers(path="/v1/crawl"), path="/v1/scrape")
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    _assert_challenged(app, sent)


@pytest.mark.asyncio
async def test_unset_internal_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no configured token, presenting one must not grant free access."""
    monkeypatch.delenv("PRY_INTERNAL_TOKEN", raising=False)
    app = _StubApp()
    scope = _scope(_internal_headers())
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    _assert_challenged(app, sent)
    assert not internal_request(scope, dict(scope["headers"]))


@pytest.mark.asyncio
async def test_owner_key_still_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner (PRY_API_KEY) branch is unchanged by the internal path."""
    monkeypatch.setenv("PRY_API_KEY", "owner-secret")
    monkeypatch.delenv("PRY_INTERNAL_TOKEN", raising=False)
    app = _StubApp()
    scope = _scope([(b"x-api-key", b"owner-secret")])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "owner request must reach the app"
    assert sent[0]["status"] == 200
    assert scope.get("x402_verified", {}).get("payment_id") == "owner"


@pytest.mark.asyncio
async def test_external_bearer_does_not_get_internal_free_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner Bearer caller is not internal: no free marker, no payment.

    Pre-existing behaviour (unchanged here): a Bearer credential is handed to
    the inner auth + billing layer, which is the hosted-API-key path. What this
    test pins is that the internal token adds nothing to it.
    """
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv("PRY_API_KEY", "owner-secret")
    app = _StubApp()
    scope = _scope(
        [
            (b"authorization", b"Bearer not-the-owner-key"),
            *[(k, b"bogus") for k in (INTERNAL_TOKEN_HEADER, INTERNAL_SIG_HEADER)],
        ]
    )
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "bearer traffic goes to the inner auth/billing path"
    assert sent[0]["status"] == 200
    assert "x402_verified" not in scope, "a bogus internal token must not mark the scope"


@pytest.mark.asyncio
async def test_external_anonymous_still_pays(monkeypatch: pytest.MonkeyPatch) -> None:
    """The revenue path is unchanged: anonymous paid calls still get 402."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.delenv("PRY_API_KEY", raising=False)
    app = _StubApp()
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), _scope([]))
    _assert_challenged(app, sent)
