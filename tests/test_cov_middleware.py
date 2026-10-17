"""Branch coverage for the fail-closed ASGI auth policy."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from pry.core import middleware_auth as mwa

if TYPE_CHECKING:
    import pytest


def _scope(peer: str = "10.0.0.1", xff: str = "", bearer: str = "") -> dict:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return {"type": "http", "headers": headers, "client": (peer, 1234), "path": "/v1/x"}


def test_trusted_proxy_parsing_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    assert mwa._parse_trusted_proxy("not-an-ip") is None
    assert mwa._parse_trusted_proxy("10.0.0.0/8") == ipaddress.ip_network("10.0.0.0/8")

    monkeypatch.setattr(mwa, "_TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("10.0.0.0/8"),))
    assert mwa._is_trusted_proxy("") is False
    assert mwa._is_trusted_proxy("unknown") is False
    assert mwa._is_trusted_proxy("999.1.1.1") is False
    assert mwa._is_trusted_proxy("10.2.3.4") is True
    assert mwa._is_trusted_proxy("11.2.3.4") is False


def test_xff_chain_malformed_and_trusted_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mwa, "_TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("10.0.0.0/8"),))
    assert mwa._xff_hops("1.2.3.4") == "1.2.3.4"
    assert mwa._xff_hops("1.2.3.4, 10.0.0.9") == "1.2.3.4"
    assert mwa._xff_hops("1.2.3.4,,5.6.7.8") is None
    assert mwa._xff_hops("1.2.3.4, garbage") is None
    assert mwa._xff_hops("10.0.0.1, 10.0.0.2") == "10.0.0.1"


def test_resolve_client_ip_rejects_spoofable_chains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mwa, "_TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("10.0.0.0/8"),))
    assert mwa.resolve_client_ip({"client": ()}) is None
    assert mwa.resolve_client_ip({"client": ("unknown", 1)}) is None
    assert mwa.resolve_client_ip(_scope("10.0.0.5")) == "10.0.0.5"
    assert mwa.resolve_client_ip(_scope("8.8.8.8", "1.2.3.4")) is None
    assert mwa.resolve_client_ip(_scope("10.0.0.5", "1.2.3.4, garbage")) is None
    assert mwa.resolve_client_ip(_scope("10.0.0.5", "1.2.3.4")) == "1.2.3.4"


def test_keyless_allowance_env_tristate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ALLOW_KEYLESS_LOOPBACK", "1")
    assert mwa.keyless_loopback_allowed() is True
    monkeypatch.setenv("PRY_ALLOW_KEYLESS_LOOPBACK", "0")
    assert mwa.keyless_loopback_allowed() is False
    monkeypatch.delenv("PRY_ALLOW_KEYLESS_LOOPBACK")
    monkeypatch.setattr(mwa.settings, "environment", "prod", raising=False)
    assert mwa.keyless_loopback_allowed() is False
    monkeypatch.setattr(mwa.settings, "environment", "dev", raising=False)
    assert mwa.keyless_loopback_allowed() is True


def test_loopback_detection_boundaries() -> None:
    assert mwa.is_loopback_client("127.0.0.5") is True
    assert mwa.is_loopback_client("::ffff:127.0.0.1") is True
    assert mwa.is_loopback_client("testclient") is True
    assert mwa.is_loopback_client("") is False
    assert mwa.is_loopback_client("8.8.8.8") is False


def test_x402_identity_binds_payment_or_batch() -> None:
    paid = {"x402_verified": {"payment_id": "pay_1", "caller": "alice"}}
    assert mwa._apply_x402_identity(paid) is True
    assert paid["pry_api_key"]["key_id"] == "x402:pay_1"
    assert paid["pry_api_key"]["user_id"] == "x402:alice"
    batch = {"x402_verified": {"batch_id": "b_1"}}
    mwa._apply_x402_identity(batch)
    assert batch["pry_api_key"]["key_id"] == "x402:b_1"
    assert batch["pry_api_key"]["user_id"] == "x402:unknown"


def test_master_key_mismatch_and_jwt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mwa.settings, "api_key", "master", raising=False)
    monkeypatch.setattr(mwa, "is_jwt", lambda _t: False)
    assert mwa.request_authorized(_scope(bearer="wrong")) is False
    monkeypatch.setattr(mwa, "is_jwt", lambda t: t == "a.b.c")
    monkeypatch.setattr(mwa, "validate_rmi_jwt", lambda t: {"sub": "u"} if t == "a.b.c" else None)
    assert mwa.request_authorized(_scope(bearer="a.b.c")) is True
    assert mwa.request_authorized(_scope(bearer="x.y.z")) is False


def test_keyless_remote_client_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mwa.settings, "api_key", "", raising=False)
    monkeypatch.setenv("PRY_ALLOW_KEYLESS_LOOPBACK", "1")
    assert mwa.request_authorized(_scope("8.8.8.8")) is False
    assert mwa.request_authorized(_scope("127.0.0.1")) is True


def test_request_authorized_x402_and_keyless_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    paid = _scope("127.0.0.1")
    paid["x402_verified"] = {"payment_id": "p1"}
    assert mwa.request_authorized(paid) is True
    assert paid["pry_api_key"]["key_id"] == "x402:p1"

    monkeypatch.setattr(mwa.settings, "api_key", "", raising=False)
    monkeypatch.setenv("PRY_ALLOW_KEYLESS_LOOPBACK", "0")
    assert mwa.request_authorized(_scope("127.0.0.1")) is False
