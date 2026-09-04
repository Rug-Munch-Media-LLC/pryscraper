"""Pry — server attestation sign/verify over the x402 payment-required body.

Key resolution, per-accept ECDSA signing, verification (with freshness
window + clock-skew tolerance), attested price binding, and the Base64
encode step that attaches the attestation. See :mod:`.digest` for the
canonical payload/digest scheme.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any

from pry.payments.x402.scheme.digest import _eth_keys  # type: ignore[attr-defined]

from .digest import (
    X402_ATTEST_ALGORITHM,
    X402_ATTEST_DOMAIN,
    X402_ATTEST_KEY_ENV,
    X402_ATTEST_MAX_AGE_SECONDS,
    X402_ATTEST_MAX_SKEW_SECONDS,
    X402_ATTEST_SECRET_ENV,
    X402_ATTEST_VERSION,
    _attestation_digest,
)
from .networks import normalize_network_id

logger = logging.getLogger(__name__)


def _scheme_pkg() -> Any:
    """The scheme package module, resolved lazily at call time.

    The attestation key cache lives on the package (``_attest_key_cache``)
    so tests that patch ``pry.payments.x402.scheme._attest_key_cache`` keep
    working after the module→package split.
    """
    import pry.payments.x402.scheme as pkg

    return pkg


def _attestation_private_key() -> Any:
    """Resolve the attestation private key (cached); None when unconfigured."""
    pkg = _scheme_pkg()
    if pkg._attest_key_cache is not None:
        return pkg._attest_key_cache
    if not _eth_keys:
        return None
    raw = os.getenv(X402_ATTEST_KEY_ENV, "").strip()
    if raw:
        raw = raw[2:] if raw.lower().startswith("0x") else raw
        try:
            pkg._attest_key_cache = _eth_keys.PrivateKey(bytes.fromhex(raw))
            return pkg._attest_key_cache
        except (ValueError, TypeError):
            logger.warning("x402_attest_key_invalid_ignored", extra={"env": X402_ATTEST_KEY_ENV})
    fac = os.getenv("PRY_X402_FACILITATOR_KEY", "").strip()
    if fac:
        fac = fac[2:] if fac.lower().startswith("0x") else fac
        try:
            pkg._attest_key_cache = _eth_keys.PrivateKey(bytes.fromhex(fac))
            return pkg._attest_key_cache
        except (ValueError, TypeError):
            logger.warning(
                "x402_attest_key_invalid_ignored", extra={"env": "PRY_X402_FACILITATOR_KEY"}
            )
    secret = os.getenv(X402_ATTEST_SECRET_ENV, "").strip()
    if secret:
        # Derive a key deterministically from a configured secret. Never hardcoded.
        pkg._attest_key_cache = _eth_keys.PrivateKey(hashlib.sha256(secret.encode()).digest())
        return pkg._attest_key_cache
    return None


def attestation_signer_address() -> str:
    """Return the attestation signer checksum address ("" when unconfigured)."""
    key = _attestation_private_key()
    if key is None:
        return ""
    return str(key.public_key.to_address())


def attest_payment_required(body: dict[str, Any]) -> dict[str, Any]:
    """Return ``body`` with a server attestation attached (non-mutating, idempotent).

    When no attestation key is configured, or ``body`` already carries an
    ``attestation``, ``body`` is returned unchanged (backward compatible).
    Otherwise a shallow copy is produced with ``body["attestation"]`` holding
    the domain, version, algorithm, nonce, ``issued_at``, signer address and a
    per-accept recoverable ECDSA signature. The caller's dict is never mutated
    so compaction/trim consumers keep the clean body.
    """
    if not isinstance(body, dict):
        return body
    if body.get("attestation") is not None:
        return body
    key = _attestation_private_key()
    if key is None:
        return body
    accepts = body.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        return body  # nothing to attest
    nonce = uuid.uuid4().hex
    issued_at = int(time.time())
    signer = key.public_key.to_address()
    signatures: list[dict[str, Any]] = []
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            continue
        digest = _attestation_digest(issued_at, nonce, index, accept)
        sig = key.sign_msg_hash(digest)
        signatures.append({"index": index, "signature": sig.to_bytes().hex()})
    attested = dict(body)
    attested["attestation"] = {
        "version": X402_ATTEST_VERSION,
        "algorithm": X402_ATTEST_ALGORITHM,
        "domain": X402_ATTEST_DOMAIN,
        "nonce": nonce,
        "issued_at": issued_at,
        "signer": signer,
        "accepts": signatures,
    }
    return attested


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
        return {
            "verified": False,
            "reason": "body not a mapping",
            "attested": False,
            "signer": "",
            "signer_ok": False,
        }
    attest = body.get("attestation")
    if not isinstance(attest, dict):
        return {
            "verified": False,
            "reason": "no attestation present",
            "attested": False,
            "signer": "",
            "signer_ok": False,
        }
    signer = str(attest.get("signer", ""))
    if not _eth_keys:
        return {
            "verified": False,
            "reason": "attestation crypto unavailable",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    if int(attest.get("version", 0)) != X402_ATTEST_VERSION:
        return {
            "verified": False,
            "reason": "unsupported attestation version",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    if attest.get("algorithm") != X402_ATTEST_ALGORITHM:
        return {
            "verified": False,
            "reason": "unsupported attestation algorithm",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    nonce = str(attest.get("nonce", ""))
    issued_at = int(attest.get("issued_at", 0) or 0)
    if issued_at <= 0:
        return {
            "verified": False,
            "reason": "attestation missing issued_at",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    now = int(time.time())
    if issued_at - now > X402_ATTEST_MAX_SKEW_SECONDS:
        return {
            "verified": False,
            "reason": (
                "attestation issued_at in the future beyond clock-skew tolerance "
                f"(> {X402_ATTEST_MAX_SKEW_SECONDS}s) — fetch a fresh 402 challenge"
            ),
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    if now - issued_at > X402_ATTEST_MAX_AGE_SECONDS:
        return {
            "verified": False,
            "reason": (
                f"attestation expired (issued_at older than {X402_ATTEST_MAX_AGE_SECONDS}s) "
                "— fetch a fresh 402 challenge"
            ),
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    sig_map = {
        int(s.get("index", -1)): str(s.get("signature", ""))
        for s in attest.get("accepts", [])
        if isinstance(s, dict)
    }
    accepts = body.get("accepts")
    if not isinstance(accepts, list):
        return {
            "verified": False,
            "reason": "no accepts to verify",
            "attested": True,
            "signer": signer,
            "signer_ok": False,
        }
    for index, accept in enumerate(accepts):
        if not isinstance(accept, dict):
            return {
                "verified": False,
                "reason": f"accept {index} not a mapping",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        raw_sig = sig_map.get(index, "")
        if not raw_sig:
            return {
                "verified": False,
                "reason": f"missing signature for accept {index}",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        try:
            signature = _eth_keys.Signature(bytes.fromhex(raw_sig))
            digest = _attestation_digest(issued_at, nonce, index, accept)
            recovered = signature.recover_public_key_from_msg_hash(digest).to_address()
        except (ValueError, TypeError):
            return {
                "verified": False,
                "reason": f"invalid signature for accept {index}",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
        if not signer or recovered != signer:
            return {
                "verified": False,
                "reason": (
                    f"signature mismatch for accept {index} (tampered payTo/amount/network?)"
                ),
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
    signer_ok = True
    if expected_signer:
        signer_ok = signer.lower() == expected_signer.lower()
        if not signer_ok:
            return {
                "verified": False,
                "reason": "signer not in trusted set",
                "attested": True,
                "signer": signer,
                "signer_ok": False,
            }
    return {
        "verified": True,
        "reason": "",
        "attested": True,
        "signer": signer,
        "signer_ok": signer_ok,
    }


def attested_max_amount_required(
    body: dict[str, Any],
    network: str,
    asset: str,
) -> int:
    """Extract the attested ``maxAmountRequired`` (atomic) for (network, asset).

    Price binding (audit #7): the ``maxAmountRequired`` inside a VERIFIED
    server attestation is the authoritative required amount for THAT payment —
    it was signed at challenge-issuance time, so an honest payer who
    authorized the quoted amount must not be re-priced against a live oracle
    that moved in between. Callers MUST verify the body's attestation
    (:func:`verify_payment_required_attestation`) BEFORE trusting the value
    returned here; this helper performs no crypto of its own.

    Returns the positive atomic amount of the accept matching the normalized
    (network, asset) pair, or 0 when the body is unattested / unusable / no
    accept matches (callers then fall back to the live-quote comparison).
    """
    if not isinstance(body, dict) or not isinstance(body.get("attestation"), dict):
        return 0
    network_id = normalize_network_id(str(network or ""))
    asset_upper = str(asset or "").upper()
    accepts = body.get("accepts")
    if not isinstance(accepts, list):
        return 0
    for accept in accepts:
        if not isinstance(accept, dict):
            continue
        if normalize_network_id(str(accept.get("network", ""))) != network_id:
            continue
        if str(accept.get("asset", "")).upper() != asset_upper:
            continue
        try:
            value = int(str(accept.get("maxAmountRequired", "")))
        except (ValueError, TypeError):
            return 0
        return value if value > 0 else 0
    return 0


def _encode_payment_required_body(body: dict[str, Any]) -> str:
    """Base64-encode the PaymentRequired body per x402 spec.

    Attaches a server attestation over the accepts ACTUALLY being encoded
    (see :func:`attest_payment_required`) so a client/verifier can
    cryptographically confirm that ``payToAddress`` came from the server —
    closing audit #1 (the body was previously unsigned). Non-mutating and
    idempotent; when no attestation key is configured the body is encoded
    exactly as before.
    """
    attested = attest_payment_required(body)
    return base64.b64encode(json.dumps(attested).encode()).decode()
