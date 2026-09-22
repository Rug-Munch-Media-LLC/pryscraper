"""Owner (self-hosted) requests bypass the x402 payment gate.

x402 charges external callers; the owner key (our CLI/MCP/internal services)
must pass without payment and stay accepted by the inner auth layer.
"""

import pytest

from pry.payments.x402_middleware.owner import OWNER_SCOPE_KEY, mark_owner_verified, owner_request


@pytest.fixture
def owner_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin the owner key for the duration of a test."""
    monkeypatch.setenv("PRY_API_KEY", "owner-secret")
    return "owner-secret"


def test_bearer_owner_key_passes(owner_key: str) -> None:
    """A Bearer token equal to the owner key is recognised."""
    assert owner_request({b"authorization": f"Bearer {owner_key}".encode()})


def test_x_api_key_header_passes(owner_key: str) -> None:
    """X-API-Key is accepted as an alternative owner credential."""
    assert owner_request({b"x-api-key": owner_key.encode()})


def test_wrong_or_missing_key_is_not_owner(owner_key: str) -> None:
    """Anonymous or wrong-credential callers stay on the paid path."""
    assert not owner_request({})
    assert not owner_request({b"authorization": b"Bearer not-the-key"})


def test_no_configured_key_means_no_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no owner key configured nothing is exempted."""
    monkeypatch.setenv("PRY_API_KEY", "")
    assert not owner_request({b"x-api-key": b"anything"})


def test_mark_owner_verified_sets_payment_shaped_marker() -> None:
    """The marker must be payment-shaped: middleware_auth reads payment_id."""
    scope: dict = {}
    mark_owner_verified(scope)
    marker = scope[OWNER_SCOPE_KEY]
    assert isinstance(marker, dict)
    assert marker["payment_id"] == "owner"
    assert marker["owner"] is True
