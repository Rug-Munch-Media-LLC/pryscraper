"""First-party SERVICE PRINCIPAL for the x402 internal free path.

Covers the three-way contract the fleet depends on:

* our own signed service credential reaches the resource WITHOUT payment (200),
* an anonymous external caller still gets the 402 challenge,
* an external caller with a settled payment is served (200).

Plus the principal semantics added on 2026-10-25: the signed caller is a NAMED
SERVICE (``X-Internal-Service``) constrained by ``PRY_INTERNAL_ALLOWED_SERVICES``,
every grant is audited, and the resolved service is stamped onto the payment
marker so the rate limiter buckets per service instead of per shared pseudo-tenant.

The allowlist exists because a bearer token is shared by every first-party job:
without a name allowlist, one compromised job can impersonate all of them.

The ASGI harness is the shared one in ``_gate_support`` so these tests exercise
the real ``X402Middleware``, not a lookalike.
"""

import time

import pytest

from pry.payments.x402 import settlement_gate
from pry.payments.x402.handler import X402Handler
from pry.payments.x402_middleware.enforcement import X402Middleware
from pry.payments.x402_middleware.internal import (
    INTERNAL_SIG_HEADER,
    INTERNAL_TIMESTAMP_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_signature,
)
from pry.payments.x402_middleware.internal_identity import (
    ALLOWED_SERVICES_ENV,
    INTERNAL_SERVICE_HEADER,
)
from tests.x402._gate_support import (  # noqa: F401
    CALLER,
    INTERNAL_TOKEN as TOKEN,
    PAID_PATH,
    _call,
    _scope,
    _StubApp,
    db,
    no_owner_key,
)
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401

SERVICE = "rugbrain"


def _service_headers(
    service: str | None = SERVICE, timestamp: str | None = None
) -> list[tuple[bytes, bytes]]:
    """Mint a credential whose signed caller is the SERVICE NAME (not the peer IP)."""
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    caller = service or CALLER
    sig = internal_signature(TOKEN, "POST", PAID_PATH, caller, stamp)
    headers: list[tuple[bytes, bytes]] = [
        (INTERNAL_TOKEN_HEADER, TOKEN.encode()),
        (INTERNAL_SIG_HEADER, sig.encode()),
        (INTERNAL_TIMESTAMP_HEADER, stamp.encode()),
    ]
    if service:
        headers.append((INTERNAL_SERVICE_HEADER, service.encode()))
    return headers


def _middleware(app: _StubApp) -> X402Middleware:
    return X402Middleware(app, wallet="0x0", network="base")


def _challenged(app: _StubApp, sent: list[dict]) -> None:
    assert not app.called, "an unauthorised caller must not reach the resource"
    assert sent
    assert sent[0]["status"] == 402


# ── The triad ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_service_token_reaches_resource_without_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRIAD 1: our own signed service credential is served free."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv(ALLOWED_SERVICES_ENV, SERVICE)
    app = _StubApp()
    sent = await _call(_middleware(app), _scope(_service_headers(), caller=CALLER))
    assert app.called, "the owner service must reach the resource without paying"
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_anonymous_external_caller_is_challenged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRIAD 2: no credential, no service — the paywall still answers 402."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv(ALLOWED_SERVICES_ENV, SERVICE)
    app = _StubApp()
    sent = await _call(_middleware(app), _scope([], caller=CALLER))
    _challenged(app, sent)


@pytest.mark.asyncio
async def test_settled_external_payment_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    """TRIAD 3: an external payer with a settled payment is served."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setattr(X402Handler, "refresh", lambda self: None, raising=False)
    monkeypatch.setattr(X402Handler, "is_paid", lambda self, pid, **kw: True, raising=False)
    monkeypatch.setattr(settlement_gate, "is_settled", lambda handler, pid: True)

    app = _StubApp()
    headers = [(b"x-payment-id", b"pay_external_1")]
    sent = await _call(_middleware(app), _scope(headers, caller=CALLER))
    assert app.called, "a settled external payment must buy service"
    assert sent[0]["status"] == 200


# ── Service scope ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unlisted_service_is_challenged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid token claiming a service we do not serve is rejected, not downgraded."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv(ALLOWED_SERVICES_ENV, "rugmunchbot")
    app = _StubApp()
    sent = await _call(_middleware(app), _scope(_service_headers(SERVICE), caller=CALLER))
    _challenged(app, sent)


@pytest.mark.asyncio
async def test_empty_allowlist_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No allowlist configured means no named-service path at all."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.delenv(ALLOWED_SERVICES_ENV, raising=False)
    app = _StubApp()
    sent = await _call(_middleware(app), _scope(_service_headers(SERVICE), caller=CALLER))
    _challenged(app, sent)


@pytest.mark.asyncio
async def test_no_service_header_keeps_legacy_peer_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-side callers keep working: absent the header the caller is the peer."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    app = _StubApp()
    sent = await _call(_middleware(app), _scope(_service_headers(None), caller=CALLER))
    assert app.called, "the legacy peer-bound credential must still be accepted"
    assert sent[0]["status"] == 200


# ── Audit + per-service bucket ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_is_audited(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Every first-party bypass leaves one attributable audit line."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv(ALLOWED_SERVICES_ENV, SERVICE)
    app = _StubApp()
    scope = _scope(_service_headers(), caller=CALLER)
    with caplog.at_level("INFO", logger="pry.payments.x402_middleware.internal_identity"):
        await _call(_middleware(app), scope)
    grants = [r for r in caplog.records if r.msg == "pry_internal_grant"]
    assert grants, "a granted internal bypass must be audited"
    assert getattr(grants[0], "caller", "") == SERVICE
    assert getattr(grants[0], "path", "") == PAID_PATH


@pytest.mark.asyncio
async def test_marker_carries_service_for_its_own_rate_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope marker names the service so each one gets its own limiter bucket."""
    monkeypatch.setenv("PRY_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv(ALLOWED_SERVICES_ENV, SERVICE)
    app = _StubApp()
    scope = _scope(_service_headers(), caller=CALLER)
    await _call(_middleware(app), scope)
    marker = scope.get("x402_verified") or {}
    assert marker.get("caller") == SERVICE
    assert marker.get("internal") is True
