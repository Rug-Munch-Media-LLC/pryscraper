"""Pry — self-facilitator response types + settlement error taxonomy."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import httpx

from pry.payments.x402.scheme import X402Scheme


@dataclass
class VerifyResult:
    """Outcome of a self-hosted x402 payment verification.

    Attributes:
        verified: True when the payment satisfies the EIP-3009 checks.
        reason: Human-readable failure reason (empty when verified).
        signer: Recovered/expected signer address (checksummed).
        amount_atomic: Authorized value in atomic units.
        asset: Asset symbol (e.g. "USDC").
        network: Normalized CAIP-2 network id.
        scheme: Payment scheme ("exact").
    """

    verified: bool
    reason: str = ""
    signer: str = ""
    amount_atomic: int = 0
    asset: str = ""
    network: str = ""
    scheme: str = X402Scheme.EXACT.value


class SettleErrorCode(StrEnum):
    """Taxonomy of self-hosted settlement failures.

    Classified so callers and operators can react precisely: retry on
    ``rpc_timeout``, fund the facilitator key on ``insufficient_gas``, and
    treat ``nonce_conflict`` as a re-submission hazard (never blindly
    re-broadcast — idempotency already guards this).
    """

    NOT_SETTLABLE = "not_settlable"
    WRONG_CHAIN = "wrong_chain"
    INSUFFICIENT_GAS = "insufficient_gas"
    NONCE_CONFLICT = "nonce_conflict"
    RPC_TIMEOUT = "rpc_timeout"
    RPC_ERROR = "rpc_error"


@dataclass
class SettleOutcome:
    """Result of a self-hosted settlement attempt with error taxonomy.

    ``success`` True + ``tx_hash`` set means the authorization was broadcast
    (or had already been settled — ``idempotent`` True, never double-submitted).
    On failure ``error_code`` is one of :class:`SettleErrorCode` and
    ``error_detail`` carries the underlying message.
    """

    success: bool
    tx_hash: str | None = None
    error_code: str = ""
    error_detail: str = ""
    idempotent: bool = False


# RPC error-message markers used to classify settlement failures.
_RPC_INSUFFICIENT_GAS_MARKERS = (
    "insufficient funds",
    "insufficient balance",
    "out of gas",
    "gas required exceeds allowance",
)
_RPC_NONCE_MARKERS = (
    "nonce too low",
    "nonce too high",
    "replacement transaction underpriced",
    "same nonce",
)


def _classify_settle_error(exc: BaseException) -> tuple[str, str]:
    """Map an RPC/httpx failure to a :class:`SettleErrorCode` + detail."""
    detail = str(exc)
    lowered = detail.lower()
    if isinstance(exc, httpx.TimeoutException):
        return SettleErrorCode.RPC_TIMEOUT.value, detail
    if any(marker in lowered for marker in _RPC_INSUFFICIENT_GAS_MARKERS):
        return SettleErrorCode.INSUFFICIENT_GAS.value, detail
    if any(marker in lowered for marker in _RPC_NONCE_MARKERS):
        return SettleErrorCode.NONCE_CONFLICT.value, detail
    return SettleErrorCode.RPC_ERROR.value, detail
