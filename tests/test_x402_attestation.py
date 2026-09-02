# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402 server attestation over the payment-required challenge.

Covers the audit #1 hardening: a MITM rewriting ``payToAddress`` (or the
amount / network / resource) on an attested body must fail signature
verification, so a payer can never be tricked into authorizing an attacker's
address.
"""

from __future__ import annotations

import pytest

from pry.payments.x402.scheme import (
    X402_ATTEST_KEY_ENV,
    attest_payment_required,
    attestation_signer_address,
    verify_payment_required_attestation,
)

_TEST_KEY = "0x" + "11" * 32


@pytest.fixture(autouse=True)
def _attest_key(monkeypatch):
    """Configure a deterministic attestation key + clear the module cache."""
    import pry.payments.x402.scheme as scheme_mod

    monkeypatch.setenv(X402_ATTEST_KEY_ENV, _TEST_KEY)
    monkeypatch.setattr(scheme_mod, "_attest_key_cache", None)
    yield
    monkeypatch.setattr(scheme_mod, "_attest_key_cache", None, raising=False)


def _attested_body() -> dict:
    return {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "maxAmountRequired": "49000000",
                "resource": "https://pry.dev/api/scrape",
                "description": "scrape",
                "mimeType": "application/json",
                "payToAddress": "0x1E3AC01d0fdb976179790BDD02823196A92705C9",
                "asset": "USDC",
                "extra": {"operation": "scrape"},
            }
        ],
    }


def test_attest_and_verify_happy_path() -> None:
    body = _attested_body()
    attested = attest_payment_required(body)
    assert attested is not body  # non-mutating
    assert body.get("attestation") is None  # caller's dict untouched
    assert attested["attestation"]["signer"] == attestation_signer_address()

    result = verify_payment_required_attestation(attested)
    assert result["verified"] is True
    assert result["attested"] is True
    assert result["signer_ok"] is True


def test_tampered_payto_rejected() -> None:
    """Rewriting payToAddress after signing must fail verification."""
    attested = attest_payment_required(_attested_body())
    attested["accepts"][0]["payToAddress"] = "0xAttacker00000000000000000000000000000001"
    result = verify_payment_required_attestation(attested)
    assert result["verified"] is False
    assert "signature" in result["reason"] or "signer" in result["reason"]


def test_tampered_amount_rejected() -> None:
    attested = attest_payment_required(_attested_body())
    attested["accepts"][0]["maxAmountRequired"] = "999999999"
    assert verify_payment_required_attestation(attested)["verified"] is False


def test_tampered_resource_rejected() -> None:
    attested = attest_payment_required(_attested_body())
    attested["accepts"][0]["resource"] = "https://evil.example/api/scrape"
    assert verify_payment_required_attestation(attested)["verified"] is False


def test_expected_signer_mismatch_rejected() -> None:
    """A validly-signed body from an untrusted signer fails the expected check."""
    attested = attest_payment_required(_attested_body())
    result = verify_payment_required_attestation(
        attested, expected_signer="0xDifferentSigner000000000000000000000000"
    )
    assert result["verified"] is False
    assert result["signer_ok"] is False


def test_expected_signer_match_accepted() -> None:
    signer = attestation_signer_address()
    attested = attest_payment_required(_attested_body())
    assert verify_payment_required_attestation(attested, expected_signer=signer)["verified"] is True


def test_unattested_body_reports_attested_false() -> None:
    result = verify_payment_required_attestation(_attested_body())
    assert result["verified"] is False
    assert result["attested"] is False


def test_attest_idempotent_and_no_key_passthrough(monkeypatch) -> None:
    import pry.payments.x402.scheme as scheme_mod

    body = _attested_body()
    once = attest_payment_required(body)
    twice = attest_payment_required(once)
    assert twice is once  # already attested → unchanged

    monkeypatch.setattr(scheme_mod, "_attest_key_cache", None)
    monkeypatch.delenv(X402_ATTEST_KEY_ENV, raising=False)
    monkeypatch.delenv("PRY_X402_FACILITATOR_KEY", raising=False)
    monkeypatch.delenv("PRY_X402_ATTEST_SECRET", raising=False)
    unattested = attest_payment_required(_attested_body())
    assert isinstance(unattested, dict)
    assert "attestation" not in unattested  # no key → backward-compatible passthrough


# ── Freshness: clock-skew tolerance + replay window ─────────────────────────


def _reissue(body: dict, issued_at: int) -> dict:
    """Re-sign the body's accepts with a specific issued_at (test helper).

    The digest binds issued_at, so testing freshness requires re-signing,
    not just editing the timestamp.
    """
    import time as _time
    import uuid as _uuid

    import pry.payments.x402.scheme as scheme_mod

    key = scheme_mod._attestation_private_key()
    nonce = _uuid.uuid4().hex
    signer = key.public_key.to_address()
    signatures = []
    for index, accept in enumerate(body["accepts"]):
        digest = scheme_mod._attestation_digest(issued_at, nonce, index, accept)
        sig = key.sign_msg_hash(digest)
        signatures.append({"index": index, "signature": sig.to_bytes().hex()})
    out = dict(body)
    out["attestation"] = {
        "version": scheme_mod.X402_ATTEST_VERSION,
        "algorithm": scheme_mod.X402_ATTEST_ALGORITHM,
        "domain": scheme_mod.X402_ATTEST_DOMAIN,
        "nonce": nonce,
        "issued_at": issued_at,
        "signer": signer,
        "accepts": signatures,
    }
    del _time
    return out


def test_attestation_within_skew_tolerance_accepted() -> None:
    """issued_at slightly in the future (≤ skew tolerance) must still verify."""
    import time

    body = attest_payment_required(_attested_body())
    reissued = _reissue(body, int(time.time()) + 30)
    result = verify_payment_required_attestation(reissued)
    assert result["verified"] is True


def test_attestation_future_beyond_skew_rejected_with_retry_hint() -> None:
    """An attestation dated far in the future is rejected — the reason tells
    the client to fetch a fresh 402 (the retry vehicle)."""
    import time

    body = attest_payment_required(_attested_body())
    reissued = _reissue(body, int(time.time()) + 3600)
    result = verify_payment_required_attestation(reissued)
    assert result["verified"] is False
    assert "clock-skew" in result["reason"]
    assert "fresh 402" in result["reason"]


def test_attestation_expired_rejected_with_retry_hint() -> None:
    """A captured attested body past the freshness window must not replay."""
    import time

    body = attest_payment_required(_attested_body())
    reissued = _reissue(body, int(time.time()) - 3600)
    result = verify_payment_required_attestation(reissued)
    assert result["verified"] is False
    assert "expired" in result["reason"]
    assert "fresh 402" in result["reason"]


def test_attestation_missing_issued_at_rejected() -> None:
    """An attestation without issued_at fails closed."""
    body = attest_payment_required(_attested_body())
    body["attestation"] = {k: v for k, v in body["attestation"].items() if k != "issued_at"}
    result = verify_payment_required_attestation(body)
    assert result["verified"] is False
    assert "issued_at" in result["reason"]
