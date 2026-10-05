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

from .attestation_binding import (
    attested_max_amount_required as _attested_max_amount_required,
)
from .attestation_verify import (
    verify_payment_required_attestation as _verify_payment_required_attestation,
)
from .digest import (
    X402_ATTEST_ALGORITHM,
    X402_ATTEST_DOMAIN,
    X402_ATTEST_KEY_ENV,
    X402_ATTEST_SECRET_ENV,
    X402_ATTEST_VERSION,
    _attestation_digest,
)

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

    Thin re-export of :func:`.attestation_verify.verify_payment_required_attestation`
    kept for backward compatibility (``scheme.__init__`` imports it here).
    """
    return _verify_payment_required_attestation(body, expected_signer=expected_signer)


def attested_max_amount_required(
    body: dict[str, Any],
    network: str,
    asset: str,
) -> int:
    """Extract the attested ``maxAmountRequired`` (atomic) for (network, asset).

    Thin re-export of :func:`.attestation_verify.attested_max_amount_required`
    kept for backward compatibility (``scheme.__init__`` imports it here).
    """
    return _attested_max_amount_required(body, network, asset)


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
