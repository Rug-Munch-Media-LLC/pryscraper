"""Pry — domain-separated keccak digest construction + x402 header codecs.

Canonical payload/digest for the server attestation over the
payment-required challenge, plus the Base64 PAYMENT-REQUIRED /
PAYMENT-SIGNATURE header codecs.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, cast

from .networks import normalize_network_id

# Attestation crypto: same backend the self-facilitator uses (eth_keys for
# secp256k1 ecrecover/sign, eth_utils keccak for the digest). Imported
# best-effort so the module still loads (and attestation is simply disabled)
# if the crypto deps are unavailable in a stripped runtime. Resolved lazily —
# a mock/reload never has to re-import.
try:  # pragma: no cover - depends on runtime deps
    from eth_keys import (  # type: ignore[attr-defined] # pyright: ignore[reportPrivateImportUsage]
        keys as _eth_keys,
    )
    from eth_utils import (  # type: ignore[attr-defined] # pyright: ignore[reportPrivateImportUsage]
        keccak as _keccak,
    )
except Exception:  # noqa: BLE001 - optional crypto dep; attestation disabled
    # (backward compatible) even when eth_keys/eth_utils are absent.
    _eth_keys = None  # type: ignore[assignment]
    _keccak = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Server attestation over the payment-required challenge ─────────────────
# Audit #1 (HIGH): the x402 payment-required body was unsigned — a MITM /
# proxy / shared cache could rewrite ``payToAddress`` (or the amount) and a
# payer would happily sign/authorize the attacker's address. This block
# DOMAIN-SEPARATES and SIGNS the canonical (payTo, amount, network, nonce,
# issued_at, operation) of every accept with a server key, so a client or a
# verify/settle path can recompute the digest and confirm the payTo came from
# US.
#
# Scheme (v1): ``keccak256-ecdsa-secp256k1-v1``. The canonical payload is a
# stable, ordered JSON list (no dict-key ordering ambiguity), keccak256-hashed,
# then signed with the server's secp256k1 key using the same ``eth_keys``
# backend the self-facilitator uses for EIP-3009. The recoverable 65-byte
# signature (r||s||v) is embedded per accept under ``body["attestation"]``; a
# verifier recomputes the digest and ecrecovers the signer, rejecting any
# accept whose payTo/amount/network/operation/resource/asset changed.
#
# Key source (NEVER hardcoded), precedence:
#   1. ``PRY_X402_ATTEST_KEY``      - explicit 32-byte private key hex (with/without 0x)
#   2. ``PRY_X402_FACILITATOR_KEY`` - reuse the EIP-3009 facilitator key
#   3. ``PRY_X402_ATTEST_SECRET``   - derive a key via sha256(secret) (deterministic)
#   (none)                          - body is emitted UNATTESTED (backward compatible);
#                                     ``verify_payment_required_attestation`` reports
#                                     ``attested=False`` and callers decide whether to enforce.

X402_ATTEST_DOMAIN: str = "pry-x402/attestation/v1"
X402_ATTEST_ALGORITHM: str = "keccak256-ecdsa-secp256k1-v1"
X402_ATTEST_VERSION: int = 1
X402_ATTEST_KEY_ENV: str = "PRY_X402_ATTEST_KEY"
X402_ATTEST_SECRET_ENV: str = "PRY_X402_ATTEST_SECRET"  # noqa: S105 - env var NAME, never a value
# Freshness window for a client-presented attestation. A captured attested
# 402 body must not be replayable forever; a small future tolerance absorbs
# clock skew between the issuing node and the verifying node (and in-flight
# latency). On either failure the gate answers with a FRESH 402 challenge —
# that fresh challenge IS the retry: the client re-pays against it.
X402_ATTEST_MAX_SKEW_SECONDS: int = int(os.getenv("PRY_X402_ATTEST_MAX_SKEW", "120"))
X402_ATTEST_MAX_AGE_SECONDS: int = int(os.getenv("PRY_X402_ATTEST_MAX_AGE", "600"))


def _attestation_payload(
    issued_at: int,
    nonce: str,
    index: int,
    accept: dict[str, Any],
) -> bytes:
    """Canonical, domain-separated bytes for one accept.

    Ordered JSON list (stable; dict keys are not signed directly so there is
    no ordering ambiguity). A verifier MUST rebuild the exact same list from
    the accept plus the top-level ``issued_at``/``nonce`` — any change to
    payTo, amount, network, operation, resource or asset flips the digest.
    """
    raw_extra = accept.get("extra")
    extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
    return json.dumps(
        [
            X402_ATTEST_DOMAIN,
            int(X402_ATTEST_VERSION),
            int(issued_at),
            str(nonce),
            int(index),
            str(accept.get("payToAddress", "")),
            str(accept.get("maxAmountRequired", "")),
            str(normalize_network_id(str(accept.get("network", "")))),
            str(extra.get("operation", "") or accept.get("operation", "")),
            str(accept.get("resource", "")),
            str(accept.get("asset", "")),
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def _attestation_digest(issued_at: int, nonce: str, index: int, accept: dict[str, Any]) -> bytes:
    if _keccak is None:
        raise RuntimeError("attestation crypto unavailable (eth_utils missing)")
    return _keccak(_attestation_payload(issued_at, nonce, index, accept))


def _decode_payment_signature(header: str) -> dict[str, Any] | None:  # test-only
    """Decode the PAYMENT-SIGNATURE header per x402 spec."""
    try:
        return cast("dict[str, Any]", json.loads(base64.b64decode(header).decode()))
    except (ValueError, OSError):
        return None
