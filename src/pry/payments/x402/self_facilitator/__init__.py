"""Pry — self-hosted x402 facilitator (no external facilitator / Coinbase CDP).

Implements EVM ``exact``-scheme verify + settle entirely on Pry infra:

- **verify**: ecrecover the EIP-3009 ``transferWithAuthorization`` signer
  locally (via ``eth_keys``), then validate amount >= price, recipient == the
  configured ``payTo`` wallet, validAfter/validBefore window, chain id and
  nonce. Replays are rejected by a bounded in-memory nonce set with optional
  JSON persistence (``X402_DIR/self_facilitator_nonces.json``).
- **settle**: sign + broadcast the authorization (or a plain
  ``transferFrom`` when the payer pre-approved) to the configured RPC via
  httpx, returning the tx hash (or ``None`` when not settlable / chain
  unavailable / missing key). Settlement is hardened: idempotent
  (an already-settled payment returns the existing tx hash, never
  double-submits), tracked in bounded ``pending_settlements`` /
  ``_settled_txs`` structures, and failures are classified into a
  :class:`SettleErrorCode` taxonomy (insufficient gas, nonce conflict, RPC
  timeout, wrong chain, …) via :meth:`SelfFacilitator.settle_with_details`.

Crypto: ``eth-keys`` (ecrecover + digest signing) and ``eth-account``
(transaction signing / RLP). Keccak backend is ``eth-hash[pycryptodome]``.
These are new [project] dependencies added in pyproject.toml — [REVIEW] lead
reconciles. Nothing here talks to Coinbase / CDP / any external facilitator.

The EIP-712 domain defaults to Circle USDC (name "USD Coin", version "2").
Operators using a different EIP-3009 token MUST verify the token's
domain name/version (``domain_name`` / ``domain_version`` args or
``PRY_X402_EIP712_NAME`` / ``PRY_X402_EIP712_VERSION`` env). [REVIEW]

This module is NOT wired into the ASGI middleware yet (the middleware is
out of scope for this change): to use self-facilitation end-to-end, either
call ``SelfFacilitator`` directly or attach the authorization to the router
via ``FacilitatorRouter.submit_authorization(payment_id, authorization)``.
Middleware-level plumbing is a follow-up. [REVIEW]

Split into per-concern modules (behavior unchanged):

- :mod:`.networks` — chain-id resolution + testnet rejection
- :mod:`.crypto` — ABI encoding, EIP-712/EIP-3009 digests, signature parsing
- :mod:`.response` — VerifyResult / SettleOutcome + error taxonomy
- :mod:`.nonces` — bounded replay-protection nonce store
- :mod:`.evm` — the ``SelfFacilitator`` (verify + settle)
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_DIR,
    X402_NETWORK_WALLETS,
    X402_PLACEHOLDER_WALLETS,
    X402_WALLET,
)
from pry.payments.x402.scheme import (
    get_asset_usd_price,
    normalize_network_id,
    resolve_asset_entry,
)

from .crypto import (
    _encode_address,
    _encode_bytes32,
    _encode_nonce,
    _encode_uint,
    _hex_to_bytes,
    _nonce_hex,
    _parse_signature,
    _signature_from_bytes,
    _to_int,
    build_transfer_with_authorization_digest,
    domain_separator,
    transfer_with_authorization_struct_hash,
)
from .evm import SelfFacilitator
from .networks import (
    CHAIN_ID_BY_NETWORK,
    TESTNET_CHAIN_IDS,
    TESTNET_NETWORK_IDS,
    _allow_testnets,
    _chain_id_for,
    is_testnet_network,
)
from .nonces import NonceStore
from .response import (
    SettleErrorCode,
    SettleOutcome,
    VerifyResult,
    _classify_settle_error,
)

__all__ = [
    "CHAIN_ID_BY_NETWORK",
    "TESTNET_CHAIN_IDS",
    "TESTNET_NETWORK_IDS",
    "X402_DEFAULT_ASSET",
    "X402_DIR",
    "X402_NETWORK_WALLETS",
    "X402_PLACEHOLDER_WALLETS",
    "X402_WALLET",
    "NonceStore",
    "SelfFacilitator",
    "SettleErrorCode",
    "SettleOutcome",
    "VerifyResult",
    "_allow_testnets",
    "_chain_id_for",
    "_classify_settle_error",
    "_encode_address",
    "_encode_bytes32",
    "_encode_nonce",
    "_encode_uint",
    "_hex_to_bytes",
    "_nonce_hex",
    "_parse_signature",
    "_signature_from_bytes",
    "_to_int",
    "build_transfer_with_authorization_digest",
    "domain_separator",
    "get_asset_usd_price",
    "is_testnet_network",
    "normalize_network_id",
    "resolve_asset_entry",
    "transfer_with_authorization_struct_hash",
]
