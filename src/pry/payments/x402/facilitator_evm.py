"""Pry — x402 facilitator EVM verification (EIP-7702 self-verify fallback).
Extracted from ``facilitator.py``: the EIP-7702 on-chain receipt verification
helpers — RPC key resolution (CAIP-2 → legacy short name), JSON-RPC calls,
payTo/amount matching against the tx, and the settlement receipt builder.
These are module-level functions; :class:`FacilitatorRouter` keeps thin
method wrappers for backwards compatibility (tests call them unbound with
``self=None``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.payments.x402 import (
    EIP7702_RPC,
    EIP7702_TOKEN_ADDRESSES,
    X402_TIMEOUT_SECONDS,
    X402_UNCONFIGURED_WALLET,
)
from pry.payments.x402.scheme import (
    _NATIVE_ASSETS,
    asset_to_atomic,
    normalize_network_id,
    resolve_pay_to,
)

logger = logging.getLogger(__name__)

_CAIP2_TO_SHORT: dict[str, str] = {
    v: k
    for k, v in {
        "base": "eip155:8453",
        "ethereum": "eip155:1",
        "arbitrum": "eip155:42161",
        "optimism": "eip155:10",
        "polygon": "eip155:137",
        "bnb": "eip155:56",
        "avalanche": "eip155:43114",
        "base-sepolia": "eip155:84532",
        "ethereum-sepolia": "eip155:11155111",
    }.items()
}


def _eip7702_rpc_key(network: str) -> str | None:
    """Resolve a network (CAIP-2 or short name) to its EIP7702_RPC key.

    Returns the key ONLY when a matching EIP7702_RPC entry exists, so the
    ``is not None`` guard sites never claim EIP-7702 support for a chain
    that has no RPC configured (e.g. ethereum-sepolia in the reverse map).
    """
    if network in EIP7702_RPC:
        return network
    short = _CAIP2_TO_SHORT.get(normalize_network_id(network))
    if short is not None and short in EIP7702_RPC:
        return short
    return None


ERC20_TRANSFER_SELECTOR = "0xa9059cbb"


async def rpc_call(
    client: httpx.AsyncClient,
    rpc: str,
    method: str,
    params: list[Any],
) -> dict[str, Any] | None:
    """Issue a JSON-RPC call and return the ``result`` dict (or None)."""
    import time as _time

    from pry.payments.x402.metrics import record_rpc_latency

    start = _time.monotonic()
    try:
        response = await client.post(
            rpc,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result") or None
    finally:
        record_rpc_latency("eip155", method, _time.monotonic() - start)


def eip7702_matches(
    tx: dict[str, Any],
    network: str,
    asset: str,
    amount_usd: float,
) -> tuple[bool, str]:
    """Verify an EIP-7702 tx actually paid OUR wallet at least the price.

    Returns ``(ok, reason)``. ERC-20 assets must transfer() to the
    server wallet on the asset's token contract; native assets must send
    value directly to the server wallet. Unknown assets fail closed.
    """
    pay_to = (resolve_pay_to(network) or "").lower()
    if not pay_to or pay_to == X402_UNCONFIGURED_WALLET:
        return False, "server wallet not configured"
    tx_to = str(tx.get("to") or "").lower()
    tokens = EIP7702_TOKEN_ADDRESSES.get(_eip7702_rpc_key(network) or network, {})
    if asset in tokens:
        token = tokens[asset].lower()
        if tx_to != token:
            return False, f"tx recipient {tx_to} is not {asset} token on {network}"
        calldata = str(tx.get("input") or "0x")
        if not calldata.lower().startswith(ERC20_TRANSFER_SELECTOR):
            return False, "tx is not an ERC-20 transfer()"
        if len(calldata) < 138:
            return False, "ERC-20 transfer calldata too short"
        recipient = "0x" + calldata[34:74]
        try:
            paid_atomic = int(calldata[74:138], 16)
        except ValueError as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "eip7702_matches"},
            )
            return False, "unparseable ERC-20 transfer amount"
        if recipient.lower() != pay_to:
            return False, f"transfer recipient {recipient} != server wallet {pay_to}"
        expected_atomic = asset_to_atomic(amount_usd, asset, network)
        if paid_atomic < expected_atomic:
            return (
                False,
                f"underpayment: tx paid {paid_atomic} < required {expected_atomic} atomic {asset}",
            )
        return True, ""
    if asset in _NATIVE_ASSETS:
        if tx_to != pay_to:
            return False, f"tx recipient {tx_to} != server wallet {pay_to}"
        try:
            value_atomic = int(tx.get("value") or "0x0", 16)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "eip7702_matches"},
            )
            return False, "unparseable tx value"
        expected_atomic = asset_to_atomic(amount_usd, asset, network)
        if value_atomic < expected_atomic:
            return (
                False,
                f"underpayment: tx value {value_atomic} < required {expected_atomic} "
                f"atomic {asset}",
            )
        return True, ""
    return False, f"unsupported asset {asset} for EIP-7702 self-verify on {network}"


async def eip7702_verify(
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any]:
    """EIP-7702 self-verify: poll RPC for tx receipt AND check payTo/amount.

    A successful receipt alone is NOT proof of payment. We require:
    - the tx to have been sent to the facilitator's wallet (native) or to
      the asset's token contract with a transfer() to our wallet (ERC-20);
    - the transferred value to be >= the server-side price.
    """
    rpc = EIP7702_RPC.get(_eip7702_rpc_key(network) or network)
    if not rpc:
        return {"verified": False, "reason": f"No EIP-7702 RPC for {network}"}
    try:
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            receipt = await rpc_call(client, rpc, "eth_getTransactionReceipt", [tx_hash])
            if not receipt or receipt.get("status") != "0x1":
                return {
                    "verified": False,
                    "reason": "EIP-7702 receipt not found or tx failed",
                    "settlement": receipt or None,
                    "facilitator": "eip-7702",
                }
            tx = await rpc_call(client, rpc, "eth_getTransactionByHash", [tx_hash])
            if not tx:
                return {
                    "verified": False,
                    "reason": "EIP-7702 tx not found",
                    "settlement": receipt,
                    "facilitator": "eip-7702",
                }
            ok, reason = eip7702_matches(tx, network, asset, amount_usd)
            if not ok:
                return {
                    "verified": False,
                    "reason": f"EIP-7702 payment mismatch: {reason}",
                    "settlement": receipt,
                    "facilitator": "eip-7702",
                }
            return {
                "verified": True,
                "reason": "",
                "settlement": receipt,
                "facilitator": "eip-7702",
            }
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(e), "handler": "eip7702_verify"},
        )
        return {"verified": False, "reason": f"EIP-7702 verify failed: {e}", "settlement": None}


def eip7702_settlement(
    payment_id: str,
    tx_hash: str,
    network: str,
) -> dict[str, Any]:
    """Build the EIP-7702 settlement receipt (verify leg already confirmed)."""
    return {
        "success": True,
        "transaction": tx_hash,
        "network": network,
        "payment_id": payment_id,
        "facilitator": "eip-7702",
        "settled_at": datetime.now(UTC).isoformat(),
        "note": "Verified via EIP-7702 RPC",
    }
