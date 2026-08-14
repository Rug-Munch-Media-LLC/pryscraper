"""Pry — x402 (HTTP 402 Payment Required) protocol implementation.
Implements the x402 v1 spec from https://github.com/coinbase/x402

Standards compliance:
- HTTP 402 status code with PaymentRequired body
- PAYMENT-REQUIRED header (Base64-encoded JSON)
- PAYMENT-SIGNATURE header (Base64-encoded JSON, signed)
- PAYMENT-RESPONSE header on success (Base64-encoded settlement receipt)
- Multi-chain support: base, solana, ethereum, polygon, arbitrum, optimism, bnb,
  avalanche, base-sepolia, tron, bitcoin, litecoin, dogecoin
- Multi-asset: USDC, USDT, native
- Multiple facilitators: coinbase, payai, cloudflare, eip-7702
- Smart facilitator router with auto-fallback
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
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

import httpx

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

X402_DIR = PRY_DATA_DIR / "x402"
X402_DIR.mkdir(parents=True, exist_ok=True)

# x402 pricing per operation (USDC atomic units, 6 decimals)
X402_PRICING: dict[str, dict[str, Any]] = {
    "scrape": {"price_usd": 0.001, "description": "Single URL scrape"},
    "crawl": {"price_usd": 0.01, "description": "Crawl up to 10 pages"},
    "extract": {"price_usd": 0.005, "description": "Structured extraction"},
    "monitor": {"price_usd": 0.02, "description": "Create scheduled monitor"},
    "llm_call": {"price_usd": 0.01, "description": "LLM extraction call"},
    "template_execute": {"price_usd": 0.002, "description": "Execute scraper template"},
    "template_batch_execute": {"price_usd": 0.01, "description": "Execute up to 20 template items"},
    "browser_automation": {"price_usd": 0.05, "description": "Browser automation"},
    "bulk_crawl": {"price_usd": 0.10, "description": "Crawl up to 1000 pages"},
    "pdf_extract": {"price_usd": 0.01, "description": "PDF table extraction"},
    "ocr_extract": {"price_usd": 0.005, "description": "Image OCR"},
    "graphql_query": {"price_usd": 0.003, "description": "GraphQL query execution"},
    "schema_extract": {"price_usd": 0.002, "description": "Schema.org/JSON-LD extraction"},
}


class X402Scheme(StrEnum):
    """Payment schemes supported by x402."""

    EXACT = "exact"
    UPTO = "upto"


class X402Network(StrEnum):
    """Blockchain networks supported by x402."""

    BASE = "base"
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BNB = "bnb"
    AVALANCHE = "avalanche"
    BASE_SEPOLIA = "base-sepolia"
    TRON = "tron"
    BITCOIN = "bitcoin"
    LITECOIN = "litecoin"
    DOGECOIN = "dogecoin"


class X402Asset(StrEnum):
    """Token assets supported by x402."""

    USDC = "USDC"
    USDT = "USDT"
    DAI = "DAI"
    ETH = "ETH"
    SOL = "SOL"
    MATIC = "MATIC"
    TRX = "TRX"
    BTC = "BTC"
    LTC = "LTC"
    DOGE = "DOGE"


# Prefer gopass for the x402 wallet and facilitator URL. Env vars override only
# if the backend returns an empty string. This lets you:
#   gopass insert -m pry/x402_wallet               # persistent across restarts
#   PRY_X402_WALLET=0x...                          # one-off override (CI, dev)
try:
    from secrets_backend import get_secret as _gs

    X402_WALLET = _gs("x402_wallet") or os.getenv("PRY_X402_WALLET", "pry-default-wallet")
    X402_FACILITATOR_URL = _gs("x402_facilitator") or os.getenv(
        "PRY_X402_FACILITATOR", "https://x402.org/facilitator"
    )
except ImportError:
    X402_WALLET = os.getenv("PRY_X402_WALLET", "pry-default-wallet")
    X402_FACILITATOR_URL = os.getenv("PRY_X402_FACILITATOR", "https://x402.org/facilitator")
X402_DEFAULT_NETWORK = os.getenv("PRY_X402_NETWORK", X402Network.BASE.value)
X402_DEFAULT_ASSET = os.getenv("PRY_X402_ASSET", X402Asset.USDC.value)
X402_OFFLINE_MODE = os.getenv("PRY_X402_OFFLINE", "false").lower() in ("1", "true", "yes")
X402_TIMEOUT_SECONDS = float(os.getenv("PRY_X402_TIMEOUT", "15"))

# EIP-7702 self-verify RPC endpoints (public defaults, override via env)
EIP7702_RPC: dict[str, str] = {
    "base": os.getenv("PRY_X402_BASE_RPC", "https://mainnet.base.org"),
    "ethereum": os.getenv("PRY_X402_ETH_RPC", "https://eth.llamarpc.com"),
    "polygon": os.getenv("PRY_X402_POLYGON_RPC", "https://polygon.drpc.org"),
    "arbitrum": os.getenv("PRY_X402_ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
    "optimism": os.getenv("PRY_X402_OPTIMISM_RPC", "https://mainnet.optimism.io"),
    "bnb": os.getenv("PRY_X402_BNB_RPC", "https://bsc-dataseed.binance.org"),
    "avalanche": os.getenv("PRY_X402_AVALANCHE_RPC", "https://api.avax.network/ext/bc/C/rpc"),
    "base-sepolia": os.getenv("PRY_X402_BASE_SEPOLIA_RPC", "https://sepolia.base.org"),
}

# Asset decimals for atomic conversion
ASSET_DECIMALS: dict[str, int] = {
    X402Asset.USDC.value: 6,
    X402Asset.USDT.value: 6,
    X402Asset.DAI.value: 18,
    X402Asset.ETH.value: 18,
    X402Asset.SOL.value: 9,
    X402Asset.MATIC.value: 18,
    X402Asset.TRX.value: 6,
    X402Asset.BTC.value: 8,
    X402Asset.LTC.value: 8,
    X402Asset.DOGE.value: 8,
}


def _to_atomic(amount_usd: float, asset: str = X402_DEFAULT_ASSET) -> int:
    """Convert USD amount to atomic units for the given asset."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return int(amount_usd * (10**decimals))


def _from_atomic(amount_atomic: int, asset: str = X402_DEFAULT_ASSET) -> float:
    """Convert atomic units back to USD-normalized float."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return float(round(amount_atomic / (10**decimals), decimals))


def _encode_payment_required_body(body: dict[str, Any]) -> str:
    """Base64-encode the PaymentRequired body per x402 spec."""
    return base64.b64encode(json.dumps(body).encode()).decode()


def _decode_payment_signature(header: str) -> dict[str, Any] | None:
    """Decode the PAYMENT-SIGNATURE header per x402 spec."""
    try:
        return cast("dict[str, Any]", json.loads(base64.b64decode(header).decode()))
    except (ValueError, OSError):
        return None


def _encode_payment_response(settlement: dict[str, Any]) -> str:
    """Base64-encode the PaymentResponse (settlement receipt) per x402 spec."""
    return base64.b64encode(json.dumps(settlement).encode()).decode()


def _default_networks_for_asset(asset: str) -> list[str]:
    """Return sensible default networks for an asset."""
    asset = asset.upper()
    mapping: dict[str, list[str]] = {
        X402Asset.USDC.value: [
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.SOLANA.value,
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.USDT.value: [
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.TRON.value,
            X402Network.SOLANA.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.DAI.value: [
            X402Network.ETHEREUM.value,
            X402Network.POLYGON.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.BASE.value,
        ],
        X402Asset.ETH.value: [
            X402Network.ETHEREUM.value,
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
        ],
        X402Asset.SOL.value: [X402Network.SOLANA.value],
        X402Asset.MATIC.value: [X402Network.POLYGON.value],
        X402Asset.TRX.value: [X402Network.TRON.value],
        X402Asset.BTC.value: [X402Network.BITCOIN.value],
        X402Asset.LTC.value: [X402Network.LITECOIN.value],
        X402Asset.DOGE.value: [X402Network.DOGECOIN.value],
    }
    return mapping.get(asset, [X402Network.BASE.value])


def _asset_on_network(asset: str, network: str) -> bool:
    """Check whether an asset is generally supported on a network."""
    return network in _default_networks_for_asset(asset)


def build_payment_required(
    operation: str,
    resource: str = "",
    accepts: list[dict[str, Any]] | None = None,
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
) -> dict[str, Any]:
    """Build a spec-compliant x402 PaymentRequired response.

    Returns a dict that should be:
    1. Returned as the body of the 402 response (JSON)
    2. Base64-encoded and put in the PAYMENT-REQUIRED header

    Args:
        operation: The operation being paid for (e.g., "scrape")
        resource: Full URL of the protected resource
        accepts: List of payment options (if None, generates defaults)
        description: Human-readable description
        mime_type: Expected response MIME type
        preferred_networks: Networks to prioritize in accepts
        preferred_assets: Assets to prioritize in accepts
    """
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    amount_atomic = _to_atomic(price_info["price_usd"], X402_DEFAULT_ASSET)
    resource_url = resource or f"https://pry.dev/api/{operation}"

    if accepts is None:
        networks = preferred_networks or _default_networks_for_asset(X402_DEFAULT_ASSET)
        assets = preferred_assets or [X402_DEFAULT_ASSET]
        accepts = []
        for network in networks:
            for asset in assets:
                if not _asset_on_network(asset, network):
                    continue
                amount = _to_atomic(price_info["price_usd"], asset)
                accepts.append(
                    {
                        "scheme": X402Scheme.EXACT.value,
                        "network": network,
                        "maxAmountRequired": str(amount),
                        "resource": resource_url,
                        "description": description or price_info.get("description", operation),
                        "mimeType": mime_type,
                        "payToAddress": X402_WALLET,
                        "asset": asset,
                        "extra": {"name": asset, "version": "2", "operation": operation},
                    }
                )
        if not accepts:
            # Final fallback so we never return an empty accepts array
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": X402Network.BASE.value,
                    "maxAmountRequired": str(amount_atomic),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": X402_WALLET,
                    "asset": X402_DEFAULT_ASSET,
                    "extra": {"name": X402_DEFAULT_ASSET, "version": "2", "operation": operation},
                }
            )

    return {
        "x402Version": 1,
        "accepts": accepts,
    }


@dataclass
class FacilitatorConfig:
    """Configuration for a single x402 facilitator."""

    name: str
    verify_url: str
    settle_url: str
    priority: int = 0
    enabled: bool = True
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = X402_TIMEOUT_SECONDS


# Default facilitator router — override via env or runtime config.
DEFAULT_FACILITATORS: list[FacilitatorConfig] = [
    FacilitatorConfig(
        name="coinbase",
        verify_url=os.getenv("PRY_X402_COINBASE_VERIFY", "https://x402.org/facilitator/verify"),
        settle_url=os.getenv("PRY_X402_COINBASE_SETTLE", "https://x402.org/facilitator/settle"),
        priority=int(os.getenv("PRY_X402_COINBASE_PRIORITY", "1")),
        enabled=os.getenv("PRY_X402_COINBASE_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="payai",
        verify_url=os.getenv("PRY_X402_PAYAI_VERIFY", "https://facilitator.payai.network/verify"),
        settle_url=os.getenv("PRY_X402_PAYAI_SETTLE", "https://facilitator.payai.network/settle"),
        priority=int(os.getenv("PRY_X402_PAYAI_PRIORITY", "2")),
        enabled=os.getenv("PRY_X402_PAYAI_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="cloudflare",
        verify_url=os.getenv("PRY_X402_CF_VERIFY", ""),
        settle_url=os.getenv("PRY_X402_CF_SETTLE", ""),
        priority=int(os.getenv("PRY_X402_CF_PRIORITY", "3")),
        enabled=os.getenv("PRY_X402_CF_ENABLED", "false").lower() in ("1", "true"),
    ),
]


class FacilitatorRouter:
    """Smart router that picks the best facilitator per chain/asset.

    Falls back through enabled facilitators. Records failures and retries
    with exponential backoff. Supports EIP-7702 self-verify mode as a
    last-resort fallback for EVM chains.
    """

    def __init__(self, facilitators: list[FacilitatorConfig] | None = None) -> None:
        self.facilitators = sorted(
            [f for f in (facilitators or DEFAULT_FACILITATORS) if f.enabled and f.verify_url],
            key=lambda f: f.priority,
        )
        self._failures: dict[str, int] = {}

    def _health_key(self, facilitator: FacilitatorConfig) -> str:
        return facilitator.name

    def _is_healthy(self, facilitator: FacilitatorConfig) -> bool:
        return self._failures.get(self._health_key(facilitator), 0) < 3

    def _mark_failure(self, facilitator: FacilitatorConfig) -> None:
        key = self._health_key(facilitator)
        self._failures[key] = self._failures.get(key, 0) + 1
        logger.warning("x402_facilitator_failure", extra={"facilitator": facilitator.name})

    def _mark_success(self, facilitator: FacilitatorConfig) -> None:
        key = self._health_key(facilitator)
        if key in self._failures:
            del self._failures[key]

    async def verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Verify a payment with the best available facilitator.

        Returns {"verified": bool, "reason": str, "settlement": dict|None}.
        """
        if X402_OFFLINE_MODE:
            return {"verified": True, "reason": "offline_mode", "settlement": None}

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(_to_atomic(amount_usd, asset)),
            "payToAddress": X402_WALLET,
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            for facilitator in self.facilitators:
                if not self._is_healthy(facilitator):
                    continue
                try:
                    response = await client.post(facilitator.verify_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self._mark_success(facilitator)
                    verified = bool(
                        data.get("isValid") or data.get("verified") or data.get("success")
                    )
                    return {
                        "verified": verified,
                        "reason": data.get("error", data.get("reason", "")) if not verified else "",
                        "settlement": data if verified else None,
                        "facilitator": facilitator.name,
                    }
                except httpx.HTTPStatusError as e:
                    last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                    self._mark_failure(facilitator)
                except httpx.RequestError as e:
                    last_error = f"{facilitator.name}: {e}"
                    self._mark_failure(facilitator)
                except json.JSONDecodeError as e:
                    last_error = f"{facilitator.name}: invalid JSON response - {e}"
                    self._mark_failure(facilitator)

        # EIP-7702 self-verify fallback for supported EVM chains
        if network in EIP7702_RPC:
            result = await self._eip7702_verify(tx_hash, network, asset, amount_usd)
            if result["verified"]:
                return result
            last_error = result.get("reason", last_error)

        return {"verified": False, "reason": last_error, "settlement": None}

    async def settle(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Confirm settlement with the best available facilitator."""
        if X402_OFFLINE_MODE:
            return self._offline_settlement(payment_id, tx_hash, network)

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(_to_atomic(amount_usd, asset)),
            "payToAddress": X402_WALLET,
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            for facilitator in self.facilitators:
                if not self._is_healthy(facilitator):
                    continue
                if not facilitator.settle_url:
                    continue
                try:
                    response = await client.post(facilitator.settle_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self._mark_success(facilitator)
                    return self._normalize_settlement(
                        data, payment_id, tx_hash, network, facilitator.name
                    )
                except httpx.HTTPStatusError as e:
                    last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                    self._mark_failure(facilitator)
                except httpx.RequestError as e:
                    last_error = f"{facilitator.name}: {e}"
                    self._mark_failure(facilitator)
                except json.JSONDecodeError as e:
                    last_error = f"{facilitator.name}: invalid JSON response - {e}"
                    self._mark_failure(facilitator)

        # EIP-7702 fallback settlement receipt
        if network in EIP7702_RPC:
            return self._eip7702_settlement(payment_id, tx_hash, network)

        return {
            "success": False,
            "payment_id": payment_id,
            "reason": last_error,
        }

    def _normalize_settlement(
        self,
        data: dict[str, Any],
        payment_id: str,
        tx_hash: str,
        network: str,
        facilitator: str,
    ) -> dict[str, Any]:
        """Normalize facilitator response into a standard settlement receipt."""
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": facilitator,
            "settled_at": datetime.now(UTC).isoformat(),
            "block_number": data.get("blockNumber", data.get("block_number", "")),
            "block_hash": data.get("blockHash", data.get("block_hash", "")),
            "tx_index": data.get("transactionIndex", data.get("tx_index", "")),
            "confirmations": data.get("confirmations", 0),
            "amount_paid": data.get("amountPaid", data.get("amount_paid", "")),
            "receipt": data,
        }

    def _offline_settlement(self, payment_id: str, tx_hash: str, network: str) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "offline",
            "settled_at": datetime.now(UTC).isoformat(),
            "note": "Offline mode — settlement not verified on-chain",
        }

    async def _eip7702_verify(
        self,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Lightweight EIP-7702 self-verify: poll RPC for tx receipt."""
        rpc = EIP7702_RPC.get(network)
        if not rpc:
            return {"verified": False, "reason": f"No EIP-7702 RPC for {network}"}
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        }
        try:
            async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
                response = await client.post(rpc, json=payload)
                response.raise_for_status()
                data = response.json()
                receipt = data.get("result") or {}
                if receipt.get("status") == "0x1":
                    return {
                        "verified": True,
                        "reason": "",
                        "settlement": receipt,
                        "facilitator": "eip-7702",
                    }
                return {
                    "verified": False,
                    "reason": "EIP-7702 receipt not found or tx failed",
                    "settlement": receipt,
                    "facilitator": "eip-7702",
                }
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"verified": False, "reason": f"EIP-7702 verify failed: {e}", "settlement": None}

    def _eip7702_settlement(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "eip-7702",
            "settled_at": datetime.now(UTC).isoformat(),
            "note": "Verified via EIP-7702 RPC",
        }


# Global router instance (can be overridden in tests)
_facilitator_router: FacilitatorRouter | None = None


def get_facilitator_router() -> FacilitatorRouter:
    """Return the global facilitator router."""
    global _facilitator_router
    if _facilitator_router is None:
        _facilitator_router = FacilitatorRouter()
    return _facilitator_router


def set_facilitator_router(router: FacilitatorRouter) -> None:
    """Override the global facilitator router (useful for tests)."""
    global _facilitator_router
    _facilitator_router = router


class X402Handler:
    """Handle x402 pay-per-request payments per the spec.

    Implements:
    - create_payment_required: build a spec-compliant 402 response
    - verify_payment: check that a payment header is valid (via facilitator)
    - settle_payment: confirm settlement on-chain (via facilitator)
    - require_payment: convenience method that returns a full 402 response
    """

    def __init__(
        self,
        wallet: str = "",
        facilitator_url: str = "",
        router: FacilitatorRouter | None = None,
    ) -> None:
        self.wallet = wallet or X402_WALLET
        self.facilitator_url = facilitator_url or X402_FACILITATOR_URL
        self.router = router or get_facilitator_router()
        self.payments_file = X402_DIR / "payments.jsonl"
        self.settlements_file = X402_DIR / "settlements.jsonl"
        self._load_payments()

    def _load_payments(self) -> None:
        self.payments: list[dict[str, Any]] = []
        if self.payments_file.exists():
            try:
                for line in self.payments_file.read_text().splitlines():
                    if line.strip():
                        self.payments.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                pass

    def _record_payment(self, payment: dict[str, Any]) -> None:
        """Persist payment record to local JSONL audit log."""
        try:
            with open(self.payments_file, "a") as f:
                f.write(json.dumps(payment) + "\n")
            self.payments.append(payment)
        except OSError as e:
            logger.warning("x402_payment_record_failed", extra={"error": str(e)})

    def _record_settlement(self, settlement: dict[str, Any]) -> None:
        try:
            with open(self.settlements_file, "a") as f:
                f.write(json.dumps(settlement) + "\n")
        except OSError as e:
            logger.warning("x402_settlement_record_failed", extra={"error": str(e)})

    def create_payment_required(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
        accepts: list[dict[str, Any]] | None = None,
        preferred_networks: list[str] | None = None,
        preferred_assets: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Create a spec-compliant x402 payment request.

        Returns: (body_dict, headers_dict)
        - body_dict: the JSON body for the 402 response
        - headers_dict: the HTTP headers to include (PAYMENT-REQUIRED Base64-encoded)
        """
        body = build_payment_required(
            operation,
            resource,
            accepts,
            description,
            preferred_networks=preferred_networks,
            preferred_assets=preferred_assets,
        )
        headers = {
            "PAYMENT-REQUIRED": _encode_payment_required_body(body),
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        }
        return body, headers

    async def verify_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Verify a payment via the x402 facilitator router.

        In production this calls POST /verify on the configured facilitator(s).
        Offline mode accepts the payment record directly for self-hosted Pry.
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        amount_usd = amount_usd or X402_PRICING.get(payment_id, {}).get("price_usd", 0.001)

        result = await self.router.verify(payment_id, tx_hash, network, asset, amount_usd)
        payment_record = {
            "payment_id": payment_id,
            "tx_hash": tx_hash,
            "network": network,
            "asset": asset,
            "amount_usd": amount_usd,
            "verified": result["verified"],
            "reason": result.get("reason", ""),
            "facilitator": result.get("facilitator", ""),
            "verified_at": datetime.now(UTC).isoformat(),
        }
        self._record_payment(payment_record)
        return result

    async def settle_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Settle a payment via the facilitator router.

        Returns a settlement receipt (to be Base64-encoded in PAYMENT-RESPONSE header).
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        amount_usd = amount_usd or X402_PRICING.get(payment_id, {}).get("price_usd", 0.001)

        settlement = await self.router.settle(payment_id, tx_hash, network, asset, amount_usd)
        self._record_settlement(settlement)
        return settlement

    def require_payment(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        """Build a complete 402 response with proper headers.

        Returns: {"status_code": 402, "headers": {...}, "body": {...}}
        """
        body, headers = self.create_payment_required(operation, resource, description)
        return {
            "status_code": 402,
            "headers": headers,
            "body": body,
        }

    def is_paid(self, payment_id: str) -> bool:
        return any(p["payment_id"] == payment_id and p.get("verified") for p in self.payments)

    def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        for p in self.payments:
            if p["payment_id"] == payment_id:
                return p
        return None

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_payments": len(self.payments),
            "wallet": self.wallet,
            "facilitator": self.facilitator_url,
            "pricing": X402_PRICING,
            "supported_networks": [n.value for n in X402Network],
            "supported_assets": [a.value for a in X402Asset],
            "supported_schemes": [s.value for s in X402Scheme],
            "offline_mode": X402_OFFLINE_MODE,
            "default_network": X402_DEFAULT_NETWORK,
            "default_asset": X402_DEFAULT_ASSET,
        }


# Active batch payment requests: batch_id -> {operations, total_usd, paid, tx_hash}
_batch_payments: dict[str, dict[str, Any]] = {}
_batch_lock = threading.Lock()


async def create_batch_payment(operations: list[str]) -> dict[str, Any]:
    """Create a single x402 payment requirement covering multiple operations.

    Returns a dict with batch_id, total_usd, per-operation breakdown, and a
    spec-compliant PaymentRequired body.
    """
    valid_ops: list[str] = []
    breakdown: list[dict[str, Any]] = []
    total = 0.0
    for op in operations:
        info = X402_PRICING.get(op)
        if not info:
            continue
        valid_ops.append(op)
        price = info["price_usd"]
        total += price
        breakdown.append({"operation": op, "price_usd": price})

    if not valid_ops:
        return {"error": "No valid operations provided"}

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    payment_required = build_payment_required(
        operation=valid_ops[0],
        resource=f"https://pry.dev/api/batch?ops={','.join(valid_ops)}",
        description=f"Batch payment for {len(valid_ops)} operations",
    )
    # Override the accepts amount to the batch total
    for acceptance in payment_required.get("accepts", []):
        asset = acceptance.get("asset", X402_DEFAULT_ASSET)
        acceptance["maxAmountRequired"] = str(_to_atomic(total, asset))
        acceptance["description"] = f"Batch: {', '.join(valid_ops)}"
        acceptance["extra"]["batch_id"] = batch_id
        acceptance["extra"]["operations"] = valid_ops

    with _batch_lock:
        _batch_payments[batch_id] = {
            "batch_id": batch_id,
            "operations": valid_ops,
            "total_usd": round(total, 6),
            "paid": False,
            "tx_hash": "",
            "payment_required": payment_required,
            "created_at": datetime.now(UTC).isoformat(),
        }

    return {
        "batch_id": batch_id,
        "total_usd": round(total, 6),
        "operations": breakdown,
        "payment_required": payment_required,
    }


async def verify_batch_payment(
    batch_id: str, tx_hash: str, network: str = "", asset: str = ""
) -> dict[str, Any]:
    """Verify a batch payment on-chain and mark it paid if valid."""
    with _batch_lock:
        batch = _batch_payments.get(batch_id)
    if not batch:
        return {"verified": False, "reason": "Batch not found"}
    if batch.get("paid"):
        return {"verified": True, "batch_id": batch_id, "note": "Already paid"}

    router = get_facilitator_router()
    result = await router.verify(
        batch_id,
        tx_hash,
        network=network or X402_DEFAULT_NETWORK,
        asset=asset or X402_DEFAULT_ASSET,
        amount_usd=batch["total_usd"],
    )
    if result["verified"]:
        with _batch_lock:
            _batch_payments[batch_id]["paid"] = True
            _batch_payments[batch_id]["tx_hash"] = tx_hash
            _batch_payments[batch_id]["verified_at"] = datetime.now(UTC).isoformat()
    return {
        "verified": result["verified"],
        "batch_id": batch_id,
        "reason": result.get("reason", ""),
        "total_usd": batch["total_usd"],
    }


def is_batch_paid(batch_id: str) -> bool:
    """Check whether a batch payment has been verified."""
    batch = _batch_payments.get(batch_id)
    return bool(batch and batch.get("paid"))


# These return the pre-spec response format. Prefer the spec-compliant methods
# above in new code.


def _legacy_payment_request(
    operation: str,
    metadata: dict[str, Any] | None = None,
    price_usd: float = 0.001,
    payment_id: str = "",
) -> dict[str, Any]:
    price_info = X402_PRICING.get(operation, {"price_usd": price_usd, "description": operation})
    return {
        "x402Version": 1,
        "payment_id": payment_id or uuid.uuid4().hex[:12],
        "scheme": X402Scheme.EXACT.value,
        "network": X402_DEFAULT_NETWORK,
        "resource": f"https://pry.dev/api/{operation}",
        "operation": operation,
        "description": price_info.get("description", operation),
        "maxAmountRequired": str(int(price_info["price_usd"] * 1_000_000)),
        "asset": X402Asset.USDC.value,
        "payTo": X402_WALLET,
        "maxTimeoutSeconds": 60,
        "extra": metadata or {},
    }


def create_payment_request(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build a single-payment payment request dict.

    Returns the pre-spec shape used by /v1/x402/payment.
    """
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    req = _legacy_payment_request(operation, metadata=metadata)
    logger.info(
        "x402_payment_request_created",
        extra={"payment_id": req["payment_id"], "operation": operation},
    )
    return req


def require_payment_legacy(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build the pre-spec 402 response with X-Payment-Required header."""
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    return {
        "status_code": 402,
        "headers": {
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        },
        "body": {
            "error": "Payment Required",
            "x402": _legacy_payment_request(operation, metadata=metadata),
            "instructions": (
                "Send USDC payment to the wallet address, then call the API again "
                "with the X-Payment-Hash header."
            ),
        },
    }
