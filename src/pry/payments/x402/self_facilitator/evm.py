"""Pry — the ``SelfFacilitator``: local EVM EIP-3009 verify + settle."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import httpx
from eth_account import Account
from eth_keys import keys  # type: ignore[attr-defined]
from eth_keys.datatypes import PrivateKey
from eth_utils import to_checksum_address  # type: ignore[attr-defined]

from pry.payments.x402 import (
    X402_DEFAULT_ASSET,
    X402_SELF_FACILITATOR_KEY,
    X402_SELF_FACILITATOR_RPC,
    X402_TIMEOUT_SECONDS,
)
from pry.payments.x402.scheme import normalize_network_id

from .crypto import (
    _TRANSFER_FROM_SELECTOR,
    _TRANSFER_WITH_AUTH_SELECTOR,
    _encode_address,
    _encode_bytes32,
    _encode_nonce,
    _encode_uint,
    _nonce_hex,
    _parse_signature,
    _to_int,
    build_transfer_with_authorization_digest,
)
from .networks import _allow_testnets, _chain_id_for, is_testnet_network
from .nonces import NonceStore
from .response import SettleErrorCode, SettleOutcome, VerifyResult, _classify_settle_error

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _pkg() -> Any:
    """The self_facilitator package module, resolved lazily at call time.

    Wallet config and the scheme seams (``X402_WALLET``,
    ``X402_PLACEHOLDER_WALLETS``, ``resolve_asset_entry``,
    ``get_asset_usd_price``) are read through the package so tests that patch
    ``pry.payments.x402.self_facilitator.<name>`` keep working after the
    module→package split.
    """
    import pry.payments.x402.self_facilitator as pkg

    return pkg


# Fixed gas limit fallback for ERC-20 settlement if eth_estimateGas is
# unavailable (USDC transferWithAuthorization costs ~65k; 100k is safe).
_DEFAULT_TX_GAS = 100_000


class SelfFacilitator:
    """Self-hosted x402 facilitator (EVM ``exact`` scheme).

    Args:
        pay_to: Receiving wallet. Must equal the authorization's ``to``.
            Defaults to ``X402_WALLET``; verification fails closed while the
            wallet is the ``X402_UNCONFIGURED_WALLET`` placeholder.
        facilitator_key: EVM private key used to pay gas when broadcasting
            settlement. Optional for verify; required for settle.
        rpc_url: JSON-RPC endpoint for settlement broadcast (optional; verify
            is fully local).
        domain_name / domain_version: EIP-712 domain of the EIP-3009 token
            (defaults to Circle USDC "USD Coin" / "2").
        nonce_path: JSON file backing the nonce store (defaults to
            ``X402_DIR/self_facilitator_nonces.json``).
        max_nonces: Bound of the in-memory replay set.
        transport: Optional httpx transport (tests).
        max_settled: Bound of the idempotent settled-tx tracker.
        max_pending: Bound of the in-flight pending-settlement tracker.
    """

    def __init__(
        self,
        *,
        pay_to: str = "",
        facilitator_key: str = "",
        rpc_url: str = "",
        domain_name: str = "",
        domain_version: str = "",
        nonce_path: Path | str | None = None,
        max_nonces: int = 10_000,
        timeout_seconds: float = X402_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        max_settled: int = 10_000,
        max_pending: int = 10_000,
    ) -> None:
        self.pay_to = self._normalize_address(pay_to or _pkg().X402_WALLET)
        self.facilitator_key = facilitator_key or X402_SELF_FACILITATOR_KEY
        self.rpc_url = rpc_url or X402_SELF_FACILITATOR_RPC
        self.domain_name = domain_name or os.getenv("PRY_X402_EIP712_NAME", "USD Coin")
        self.domain_version = domain_version or os.getenv("PRY_X402_EIP712_VERSION", "2")
        self.timeout_seconds = timeout_seconds
        self.nonces = NonceStore(
            path=nonce_path or _pkg().X402_DIR / "self_facilitator_nonces.json",
            max_size=max_nonces,
        )
        self._transport = transport
        key_hex = self.facilitator_key.removeprefix("0x") if self.facilitator_key else ""
        self._signer: PrivateKey | None = (
            PrivateKey(bytes.fromhex(key_hex)) if len(key_hex) == 64 else None
        )
        self._acct: Any = Account.from_key(bytes.fromhex(key_hex)) if self._signer else None
        # Settlement hardening: bounded idempotency + in-flight trackers.
        self._settled_txs: OrderedDict[str, Any] = OrderedDict()
        self._max_settled = max(int(max_settled), 1)
        self._pending_settlements: OrderedDict[str, Any] = OrderedDict()
        self._max_pending = max(int(max_pending), 1)

    # ── settlement trackers ──────────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """Number of settlement attempts currently in-flight (pending)."""
        return sum(1 for s in self._pending_settlements.values() if s.get("status") == "pending")

    def _settlement_id(self, payment: dict[str, Any]) -> str:
        """Idempotency key for a payment: payment_id, else EIP-3009 nonce key."""
        pid = str(payment.get("payment_id") or "").strip()
        if pid:
            return pid
        auth = payment.get("authorization")
        if not isinstance(auth, dict) or auth.get("nonce") is None:
            return ""
        network = normalize_network_id(str(payment.get("network") or ""))
        asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()
        entry = _pkg().resolve_asset_entry(network, asset)
        chain_id = _chain_id_for(network) or 0
        token = str(entry["contract"]).lower() if entry else ""
        return f"nonce:{chain_id}:{token}:{_nonce_hex(auth.get('nonce'))}"

    def _mark_pending(self, payment_id: str) -> None:
        self._pending_settlements[payment_id] = {
            "status": "pending",
            "started_at": time.time(),
        }
        self._trim(self._pending_settlements, self._max_pending)

    def _mark_settled(self, payment_id: str, tx_hash: str) -> None:
        entry = self._pending_settlements.get(payment_id)
        if entry is None:
            entry = {}
            self._pending_settlements[payment_id] = entry
        entry["status"] = "settled"
        entry["tx_hash"] = tx_hash
        entry["settled_at"] = time.time()
        self._settled_txs[payment_id] = tx_hash
        self._settled_txs.move_to_end(payment_id)
        self._trim(self._settled_txs, self._max_settled)

    def _mark_pending_failed(self, payment_id: str, code: str, detail: str) -> None:
        entry = self._pending_settlements.get(payment_id)
        if entry is None:
            entry = {}
            self._pending_settlements[payment_id] = entry
        entry["status"] = "failed"
        entry["error_code"] = code
        entry["error_detail"] = detail
        entry["failed_at"] = time.time()

    @staticmethod
    def _trim(ordered: OrderedDict[str, Any], max_size: int) -> None:
        while len(ordered) > max_size:
            ordered.popitem(last=False)

    @staticmethod
    def _normalize_address(value: str) -> str:
        try:
            return to_checksum_address(value)
        except (ValueError, TypeError):
            return value

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)

    async def _rpc_call(self, client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
        """Issue a JSON-RPC call against ``self.rpc_url``; returns result or None."""
        if not self.rpc_url:
            return None
        response = await client.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise ValueError(f"RPC error {method}: {data['error']}")
        return data.get("result") if isinstance(data, dict) else None

    # ── verify ───────────────────────────────────────────────────────────────

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        """Verify an EVM ``exact`` payment entirely locally.

        ``payment`` must carry:
        - ``network`` (legacy name or CAIP-2), ``asset``, ``amount_usd``
          (minimum required USD);
        - ``authorization``: the EIP-3009 ``transferWithAuthorization``
          fields + signature (``from``, ``to``, ``value``, ``validAfter``,
          ``validBefore``, ``nonce`` and either ``signature`` (65-byte hex) or
          ``v``/``r``/``s``).

        Returns a :class:`VerifyResult`. Replays are rejected via the nonce
        store. The signer recovery, amount, recipient, validity window, chain
        id and asset support are all validated; anything off fails closed.
        """
        network = normalize_network_id(str(payment.get("network") or ""))
        asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()
        try:
            amount_usd = float(payment.get("amount_usd") or 0.0)
        except (TypeError, ValueError):
            amount_usd = 0.0

        # Testnet rejection (fix #2): a free-faucet testnet authorization must
        # never verify as a real payment unless explicitly allowed (dev/test
        # only, debug-gated). Fail closed in production.
        if is_testnet_network(network) and not _allow_testnets():
            return VerifyResult(
                False,
                f"testnet {network!r} rejected on live verify path — "
                "set PRY_X402_ALLOW_TESTNETS=true with DEBUG to enable for dev/test",
                asset=asset,
                network=network,
            )

        entry = _pkg().resolve_asset_entry(network, asset)
        if entry is None:
            return VerifyResult(
                False,
                f"asset {asset!r} not supported on {network}",
                asset=asset,
                network=network,
            )
        verification = entry.get("verification")
        if verification != "eip3009":
            return VerifyResult(
                False,
                f"verification method {verification!r} is not EIP-3009 — "
                "self-facilitator supports eip3009 assets only",
                asset=asset,
                network=network,
            )
        auth = payment.get("authorization")
        if not isinstance(auth, dict) or not auth:
            return VerifyResult(
                False,
                "missing EIP-3009 transferWithAuthorization in payment",
                asset=asset,
                network=network,
            )

        if self.pay_to in _pkg().X402_PLACEHOLDER_WALLETS:
            return VerifyResult(
                False, "server wallet (payTo) not configured", asset=asset, network=network
            )

        chain_id = _chain_id_for(network)
        if chain_id is None:
            return VerifyResult(
                False, f"no EVM chain id known for {network}", asset=asset, network=network
            )
        if auth.get("chainId") is not None:
            try:
                if _to_int(auth["chainId"]) != chain_id:
                    return VerifyResult(
                        False,
                        f"authorization chainId {auth['chainId']} != configured {chain_id}",
                        asset=asset,
                        network=network,
                    )
            except ValueError:
                return VerifyResult(
                    False, "unparseable authorization chainId", asset=asset, network=network
                )

        # Recover the signer first — tampered fields (amount, recipient, …)
        # change the digest and therefore the recovered signer.
        signature = _parse_signature(auth)
        if signature is None:
            return VerifyResult(False, "malformed EIP-3009 signature", asset=asset, network=network)
        try:
            from_address = to_checksum_address(str(auth.get("from") or ""))
        except (ValueError, TypeError):
            return VerifyResult(
                False, "missing/invalid authorization 'from'", asset=asset, network=network
            )
        try:
            digest = build_transfer_with_authorization_digest(
                from_address=from_address,
                to_address=self._normalize_address(str(auth.get("to") or "")),
                value=_to_int(auth.get("value")),
                valid_after=_to_int(auth.get("validAfter") or 0),
                valid_before=_to_int(auth.get("validBefore") or 0),
                nonce=auth.get("nonce"),
                chain_id=chain_id,
                token_address=str(entry["contract"]),
                name=self.domain_name,
                version=self.domain_version,
            )
            recovered = keys.PublicKey.recover_from_msg_hash(digest, signature)
        except (ValueError, TypeError) as e:
            return VerifyResult(
                False, f"cannot verify authorization: {e}", asset=asset, network=network
            )
        recovered_address = to_checksum_address(recovered.to_address())
        if recovered_address != from_address:
            return VerifyResult(
                False,
                f"signer {recovered_address} != authorization from {from_address}",
                asset=asset,
                network=network,
            )

        # Amount: authorized value must be >= the server-side required amount.
        #
        # Price binding (audit #7): when the payment carries an ATTESTED
        # required amount (``attested_required_atomic`` — populated by the
        # enforcement gate only after the echoed 402 body's server attestation
        # verified), that SIGNED ``maxAmountRequired`` is the authoritative
        # required amount for THIS payment. An honest payer who authorized the
        # challenge-quoted amount must not be rejected because the live oracle
        # moved between challenge and payment. Fail-closed is preserved:
        # paying LESS than the attested amount is still underpayment, and
        # overpayment stays allowed. Without an attested amount the previous
        # live-oracle/static comparison applies (backward compatible).
        try:
            value = _to_int(auth.get("value"))
        except ValueError:
            return VerifyResult(
                False, "unparseable authorization value", asset=asset, network=network
            )
        decimals = int(entry.get("decimals", 6))
        attested_atomic = 0
        try:
            attested_atomic = int(payment.get("attested_required_atomic") or 0)
        except (TypeError, ValueError):
            attested_atomic = 0
        if attested_atomic > 0:
            required_atomic = attested_atomic
        else:
            quote = await _pkg().get_asset_usd_price(asset, network)
            if not quote.usd or quote.usd <= 0:
                return VerifyResult(
                    False, f"no USD price available for {asset}", asset=asset, network=network
                )
            required_atomic = (
                round(amount_usd / quote.usd * (10**decimals)) if amount_usd > 0 else 1
            )
        if value < required_atomic:
            return VerifyResult(
                False,
                f"underpayment: authorized {value} < required {required_atomic} atomic {asset}",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Recipient must be our configured payTo wallet.
        try:
            to_address = to_checksum_address(str(auth.get("to") or ""))
        except (ValueError, TypeError):
            return VerifyResult(
                False, "missing/invalid authorization 'to'", asset=asset, network=network
            )
        if to_address != self.pay_to:
            return VerifyResult(
                False,
                f"recipient {to_address} != configured payTo {self.pay_to}",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Validity window (Unix seconds). validBefore == 0 means no expiry
        # (some clients omit it); otherwise must not be in the past.
        now = int(time.time())
        try:
            valid_after = _to_int(auth.get("validAfter") or 0)
            valid_before = _to_int(auth.get("validBefore") or 0)
        except ValueError:
            return VerifyResult(
                False,
                "unparseable authorization validity window",
                signer=recovered_address,
                asset=asset,
                network=network,
            )
        if now < valid_after:
            return VerifyResult(
                False,
                "authorization not valid yet (validAfter in the future)",
                signer=recovered_address,
                asset=asset,
                network=network,
            )
        if valid_before and now >= valid_before:
            return VerifyResult(
                False,
                "authorization expired (validBefore passed)",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Replay protection: the nonce must be unused (per token contract).
        nonce_key = f"{chain_id}:{str(entry['contract']).lower()}:{_nonce_hex(auth.get('nonce'))}"
        if not self.nonces.mark_used(nonce_key):
            return VerifyResult(
                False,
                "nonce already used (replay)",
                signer=recovered_address,
                amount_atomic=value,
                asset=asset,
                network=network,
            )

        return VerifyResult(
            True,
            "",
            signer=recovered_address,
            amount_atomic=value,
            asset=asset,
            network=network,
        )

    # ── settle ───────────────────────────────────────────────────────────────

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

        # Testnet rejection (fix #2) — never broadcast settlement on a testnet
        # unless explicitly allowed (dev/test only, debug-gated).
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

        # Idempotency: an already-settled payment returns the existing hash —
        # never re-broadcast (double-spend of the same authorization).
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
                # Refuse to broadcast on the wrong chain.
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
                    except ValueError:
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

    async def _send_tx(
        self,
        client: httpx.AsyncClient,
        *,
        to: str,
        data: str,
        chain_id: int,
        value: int,
    ) -> str | None:
        """Fetch nonce/gas, sign a legacy tx, broadcast, return tx hash."""
        assert self._acct is not None
        payer = self._signer.public_key.to_checksum_address() if self._signer else ""
        nonce_hex = await self._rpc_call(client, "eth_getTransactionCount", [payer, "pending"])
        if nonce_hex is None:
            return None
        nonce = int(str(nonce_hex), 16)

        gas_limit = _DEFAULT_TX_GAS
        try:
            estimated = await self._rpc_call(
                client,
                "eth_estimateGas",
                [{"from": payer, "to": to, "data": data, "value": hex(value)}],
            )
            if estimated is not None:
                gas_limit = int(str(estimated), 16)
        except (ValueError, httpx.HTTPError):
            pass

        gas_price_hex = await self._rpc_call(client, "eth_gasPrice", [])
        if gas_price_hex is None:
            return None
        gas_price = int(str(gas_price_hex), 16)

        signed = self._acct.sign_transaction(
            {
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": gas_limit,
                "to": to,
                "value": value,
                "data": data,
                "chainId": chain_id,
            }
        )
        raw = str(signed.raw_transaction.hex())
        result = await self._rpc_call(
            client, "eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")]
        )
        return str(result) if result else None
