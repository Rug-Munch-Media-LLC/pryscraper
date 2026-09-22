"""Gate-level regression: owner requests never hit the payment challenge.

Runs the real X402Middleware with a stub ASGI app on a paid endpoint. Guards
the self-hosted access rule (owner key = free, anonymous = 402) so a future
refactor cannot silently re-gate our own CLI/MCP/internal services.
"""

import json

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware


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


def _scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": PAID_PATH,
        "headers": headers,
        "query_string": b"",
    }


async def _call(middleware: X402Middleware, scope: dict) -> list[dict]:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


@pytest.mark.asyncio
async def test_owner_key_reaches_app_without_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid owner key passes straight through the payment gate."""
    monkeypatch.setenv("PRY_API_KEY", "owner-secret")
    app = _StubApp()
    scope = _scope([(b"x-api-key", b"owner-secret")])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "owner request must reach the app"
    assert sent, "a response must be sent"
    assert sent[0]["status"] == 200
    assert scope.get("x402_verified", {}).get("payment_id") == "owner"


@pytest.mark.asyncio
async def test_anonymous_paid_path_still_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the owner key the paid path must still return 402."""
    monkeypatch.setenv("PRY_API_KEY", "owner-secret")
    app = _StubApp()
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), _scope([]))
    assert not app.called, "anonymous request must not reach the app"
    assert sent, "a challenge response must be sent"
    assert sent[0]["status"] == 402
    body = json.loads(
        b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
        or "{}"
    )
    assert body, "402 response carries the payment challenge body"
