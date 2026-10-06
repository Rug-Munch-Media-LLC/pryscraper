"""Pry — settlement broadcast for the EVM self-facilitator.

Signs and broadcasts EIP-3009 ``transferWithAuthorization`` (or pre-approved
``transferFrom``) settlements with idempotency and error taxonomy.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from pry.payments.x402 import X402_DEFAULT_ASSET
from pry.payments.x402.scheme import normalize_network_id

from .crypto import (
    _TRANSFER_FROM_SELECTOR,
    _TRANSFER_WITH_AUTH_SELECTOR,
    _encode_address,
    _encode_bytes32,
    _encode_nonce,
    _encode_uint,
    _parse_signature,
    _to_int,
)
from .evm_common import _pkg
from .networks import _allow_testnets, _chain_id_for, is_testnet_network
from .response import SettleErrorCode, SettleOutcome, _classify_settle_error

logger = logging.getLogger(__name__)


class EVMSettleMixin:
    """Settlement broadcast for :class:`SelfFacilitator`."""

    async def settle(self, payment: dict[str, Any]) -> str | None:
        """Sign + broadcast settlement. Returns the tx hash, or None.

        Legacy contract (returns ``str | None``). For the hardened result
        with idempotency + error taxonomy use :meth:`settle_with_details`.

        Settlement order:
        1. ``transferWithAuthorization`` broadcast when the payment carries an
           authorization (anyone may broadcast; our key pays the gas);
        2. plain ``transferFrom`` when the payment is flagged ``approved``
           (payer pre-approved our wallet) — our key is the caller;
        3. otherwise None (not settlable / chain unavailable / missing key).

        Idempotent: settling an already-settled payment returns the existing
        tx hash without re-broadcasting.

        RPC calls: eth_chainId, eth_getTransactionCount, eth_estimateGas,
        eth_gasPrice, eth_sendRawTransaction.
        """
        outcome = await self.settle_with_details(payment)
        return outcome.tx_hash if outcome.success else None

    async def settle_with_details(self, payment: dict[str, Any]) -> SettleOutcome:
        """Sign + broadcast settlement with idempotency + error taxonomy.

        Never double-submits: an already-settled payment (by ``payment_id``,
        or by EIP-3009 nonce when no id is present) returns the existing tx
        hash with ``idempotent=True``. Failures are classified into
        :class:`SettleErrorCode` (insufficient gas, nonce conflict, RPC
        timeout, …) so callers can react precisely instead of guessing.
        """
        if not self.rpc_url or self._acct is None:
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail="no RPC URL or facilitator key configured",
            )

        network = normalize_network_id(str(payment.get("network") or ""))
        asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()

        if is_testnet_network(network) and not _allow_testnets():
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail=f"testnet {network!r} rejected on live settle path",
            )

        entry = _pkg().resolve_asset_entry(network, asset)
        if entry is None:
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail=f"asset {asset!r} not supported on {network}",
            )
        chain_id = _chain_id_for(network)
        if chain_id is None:
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail=f"no EVM chain id known for {network}",
            )

        settle_id = self._settlement_id(payment)
        if settle_id and settle_id in self._settled_txs:
            existing = str(self._settled_txs[settle_id])
            logger.info("x402_self_settle_idempotent", extra={"settle_id": settle_id})
            return SettleOutcome(True, tx_hash=existing, idempotent=True)

        auth = payment.get("authorization")
        if isinstance(auth, dict) and auth:
            try:
                data = self._build_transfer_with_auth_calldata(auth)
            except (ValueError, KeyError) as e:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(e), "handler": "EVMSettleMixin.settle_with_details"},
                )
                return SettleOutcome(
                    False,
                    error_code=SettleErrorCode.NOT_SETTLABLE.value,
                    error_detail=f"malformed authorization: {e}",
                )
            to_address = self._normalize_address(str(entry["contract"]))
        elif payment.get("approved"):
            data = self._build_transfer_from_calldata(payment)
            to_address = self._normalize_address(str(entry["contract"]))
        else:
            logger.info(
                "x402_self_settle_not_settlable",
                extra={"network": network, "asset": asset},
            )
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail="no authorization and payment not pre-approved",
            )

        if self.pay_to in _pkg().X402_PLACEHOLDER_WALLETS:
            return SettleOutcome(
                False,
                error_code=SettleErrorCode.NOT_SETTLABLE.value,
                error_detail="server wallet (payTo) not configured",
            )

        pid = settle_id or str(payment.get("payment_id") or "pending")
        self._mark_pending(pid)
        try:
            async with self._client() as client:
                onchain_chain = await self._rpc_call(client, "eth_chainId", [])
                if onchain_chain is not None:
                    try:
                        if int(str(onchain_chain), 16) != chain_id:
                            detail = f"RPC chain {onchain_chain} != expected {chain_id}"
                            logger.warning(
                                "x402_self_settle_wrong_chain",
                                extra={"rpc_chain": onchain_chain, "expected": chain_id},
                            )
                            self._mark_pending_failed(
                                pid, SettleErrorCode.WRONG_CHAIN.value, detail
                            )
                            return SettleOutcome(
                                False,
                                error_code=SettleErrorCode.WRONG_CHAIN.value,
                                error_detail=detail,
                            )
                    except ValueError as exc:
                        logger.warning(
                            "payments_exception_swallowed",
                            extra={
                                "error": str(exc),
                                "handler": "EVMSettleMixin.settle_with_details",
                            },
                        )
                        detail = "unparseable eth_chainId result"
                        self._mark_pending_failed(pid, SettleErrorCode.RPC_ERROR.value, detail)
                        return SettleOutcome(
                            False,
                            error_code=SettleErrorCode.RPC_ERROR.value,
                            error_detail=detail,
                        )
                tx = await self._send_tx(
                    client, to=to_address, data=data, chain_id=chain_id, value=0
                )
        except (httpx.HTTPError, httpx.RequestError, ValueError, OSError) as e:
            code, detail = _classify_settle_error(e)
            logger.warning(
                "x402_self_settle_failed",
                extra={"error_code": code, "error": detail},
            )
            self._mark_pending_failed(pid, code, detail)
            return SettleOutcome(False, error_code=code, error_detail=detail)
        if not tx:
            detail = "broadcast returned no tx hash"
            self._mark_pending_failed(pid, SettleErrorCode.RPC_ERROR.value, detail)
            return SettleOutcome(
                False, error_code=SettleErrorCode.RPC_ERROR.value, error_detail=detail
            )
        self._mark_settled(pid, tx)
        return SettleOutcome(True, tx_hash=tx)

    def _build_transfer_with_auth_calldata(self, auth: dict[str, Any]) -> str:
        """Calldata for ERC-20 ``transferWithAuthorization(...)``."""
        signature = _parse_signature(auth)
        if signature is None:
            raise ValueError("malformed EIP-3009 signature for settlement")
        v = int(signature.v)
        if v in (27, 28):
            v -= 27
        calldata = (
            _TRANSFER_WITH_AUTH_SELECTOR
            + _encode_address(str(auth["from"]))
            + _encode_address(str(auth["to"]))
            + _encode_uint(_to_int(auth["value"]))
            + _encode_uint(_to_int(auth.get("validAfter") or 0))
            + _encode_uint(_to_int(auth.get("validBefore") or 0))
            + _encode_nonce(auth.get("nonce"))
            + _encode_uint(v)
            + _encode_bytes32(signature.r.to_bytes(32, "big"))
            + _encode_bytes32(signature.s.to_bytes(32, "big"))
        )
        return "0x" + calldata.hex()

    def _build_transfer_from_calldata(self, payment: dict[str, Any]) -> str:
        """Calldata for ERC-20 ``transferFrom(payer, payTo, value)``."""
        calldata = (
            _TRANSFER_FROM_SELECTOR
            + _encode_address(str(payment.get("from") or ""))
            + _encode_address(self.pay_to)
            + _encode_uint(_to_int(payment.get("value") or 0))
        )
        return "0x" + calldata.hex()
