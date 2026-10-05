"""Pry — server attestation verification over the x402 payment-required body.

Extracted from ``scheme.attestation`` (behavior-preserving): the pure
structural/clock checks, the per-accept ECDSA recovery loop, and the trusted
signer check. Public entry point ``verify_payment_required_attestation``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import Any

from pry.payments.x402.scheme.digest import _eth_keys  # type: ignore[attr-defined]

from .digest import (
    X402_ATTEST_ALGORITHM,
    X402_ATTEST_MAX_AGE_SECONDS,
    X402_ATTEST_MAX_SKEW_SECONDS,
    X402_ATTEST_VERSION,
    _attestation_digest,
)


def _fail(reason: str, signer: str = "", attested: bool = True) -> dict[str, Any]:
    """Build the canonical failed attestation-verification result."""
    return {
        "verified": False,
        "reason": reason,
        "attested": attested,
        "signer": signer,
        "signer_ok": False,
    }


def _check_envelope(attest: dict[str, Any], signer: str) -> dict[str, Any] | None:
    """Crypto availability, version and algorithm checks. None = proceed."""
    if not _eth_keys:
        return _fail("attestation crypto unavailable", signer)
    if int(attest.get("version", 0)) != X402_ATTEST_VERSION:
        return _fail("unsupported attestation version", signer)
    if attest.get("algorithm") != X402_ATTEST_ALGORITHM:
        return _fail("unsupported attestation algorithm", signer)
    return None


def _check_freshness(attest: dict[str, Any], signer: str) -> dict[str, Any] | None:
    """issued_at presence + clock-skew/age window. None = proceed."""
    issued_at = int(attest.get("issued_at", 0) or 0)
    if issued_at <= 0:
        return _fail("attestation missing issued_at", signer)
    now = int(time.time())
    if issued_at - now > X402_ATTEST_MAX_SKEW_SECONDS:
        return _fail(
            "attestation issued_at in the future beyond clock-skew tolerance "
            f"(> {X402_ATTEST_MAX_SKEW_SECONDS}s) — fetch a fresh 402 challenge",
            signer,
        )
    if now - issued_at > X402_ATTEST_MAX_AGE_SECONDS:
        return _fail(
            f"attestation expired (issued_at older than {X402_ATTEST_MAX_AGE_SECONDS}s) "
            "— fetch a fresh 402 challenge",
            signer,
        )
    return None


def _signature_map(attest: dict[str, Any]) -> dict[int, str]:
    """Map accept index -> signature hex from the attestation's accepts."""
    return {
        int(s.get("index", -1)): str(s.get("signature", ""))
        for s in attest.get("accepts", [])
        if isinstance(s, dict)
    }


def _recover_signer(
    accept: dict[str, Any], raw_sig: str, issued_at: int, nonce: str, index: int
) -> Any:
    """Recover the signer address for one accept; None when crypto fails."""
    try:
        signature = _eth_keys.Signature(bytes.fromhex(raw_sig))
        digest = _attestation_digest(issued_at, nonce, index, accept)
        return signature.recover_public_key_from_msg_hash(digest).to_address()
    except (ValueError, TypeError):
        return None


def _verify_accept_signatures(
    body: dict[str, Any], attest: dict[str, Any], signer: str
) -> dict[str, Any] | None:
    """Verify every accept's signature against the recomputed digest."""
    nonce = str(attest.get("nonce", ""))
    issued_at = int(attest.get("issued_at", 0) or 0)
    sig_map = _signature_map(attest)
    accepts = body.get("accepts")
    if not isinstance(accepts, list):
        return _fail("no accepts to verify", signer)
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            return _fail(f"accept {index} not a mapping", signer)
        raw_sig = sig_map.get(index, "")
        if not raw_sig:
            return _fail(f"missing signature for accept {index}", signer)
        recovered = _recover_signer(accept, raw_sig, issued_at, nonce, index)
        if recovered is None:
            return _fail(f"invalid signature for accept {index}", signer)
        if not signer or recovered != signer:
            return _fail(
                f"signature mismatch for accept {index} (tampered payTo/amount/network?)",
                signer,
            )
    return None


def _check_expected_signer(signer: str, expected_signer: str) -> dict[str, Any] | None:
    """When a trusted signer is supplied, require an exact (case-insensitive) match."""
    if expected_signer and signer.lower() != expected_signer.lower():
        return _fail("signer not in trusted set", signer)
    return None


def verify_payment_required_attestation(
    body: dict[str, Any],
    expected_signer: str = "",
) -> dict[str, Any]:
    """Verify the server attestation on a payment-required body.

    Returns ``{"verified", "reason", "attested", "signer", "signer_ok"}``.

    - ``attested=False`` - no ``attestation`` on the body (no server key was
      configured at issue time). Callers decide whether to enforce; this is
      the backward-compatible path.
    - ``verified=True`` - every accept's signature validates against the
      recomputed digest AND the ecrecovered signer matches the embedded
      ``signer`` AND (when ``expected_signer`` is supplied) that signer equals
      ``expected_signer`` (trusted out-of-band). This is what a settle/verify
      path should require before trusting ``payToAddress``.
    """
    if not isinstance(body, dict):
        return _fail("body not a mapping", attested=False)
    attest = body.get("attestation")
    if not isinstance(attest, dict):
        return _fail("no attestation present", attested=False)
    signer = str(attest.get("signer", ""))
    for check in (
        _check_envelope(attest, signer),
        _check_freshness(attest, signer),
        _verify_accept_signatures(body, attest, signer),
        _check_expected_signer(signer, expected_signer),
    ):
        if check is not None:
            return check
    signer_ok = True
    if expected_signer:
        signer_ok = signer.lower() == expected_signer.lower()
    return {
        "verified": True,
        "reason": "",
        "attested": True,
        "signer": signer,
        "signer_ok": signer_ok,
    }
