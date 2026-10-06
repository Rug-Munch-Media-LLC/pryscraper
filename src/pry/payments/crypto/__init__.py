"""Crypto payment integration for Pry.
Accepts cryptocurrency payments via Coinbase Commerce, NowPayments, and BTCPay Server.
Falls back across providers for maximum reliability.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_CRYPTO = {
    "BTC": {"name": "Bitcoin", "chain": "bitcoin", "decimals": 8},
    "ETH": {"name": "Ethereum", "chain": "ethereum", "decimals": 18},
    "SOL": {"name": "Solana", "chain": "solana", "decimals": 9},
    "USDC": {"name": "USD Coin", "chain": "multi", "decimals": 6},
    "USDT": {"name": "Tether", "chain": "multi", "decimals": 6},
    "TRX": {"name": "TRON", "chain": "tron", "decimals": 6},
}

PROVIDERS = ["coinbase_commerce", "nowpayments", "btcpay"]


class CryptoPaymentError(Exception):
    pass


class CryptoPaymentProvider:
    """Base class for crypto payment providers."""

    name: str = "base"

    async def create_charge(
        self,
        amount_usd: float,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a payment charge. Returns charge info with payment URL."""
        raise NotImplementedError

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify a webhook payload from this provider."""
        raise NotImplementedError

    async def check_status(self, charge_id: str) -> dict[str, Any]:
        """Check payment status."""
        raise NotImplementedError


class CoinbaseCommerceProvider(CryptoPaymentProvider):
    """Coinbase Commerce integration."""

    name = "coinbase_commerce"

    def __init__(self, api_key: str = "", webhook_secret: str = ""):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self._base_url = "https://api.commerce.coinbase.com"

    async def create_charge(
        self,
        amount_usd: float,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise CryptoPaymentError("Coinbase Commerce API key not configured")
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/charges",
                    headers={
                        "X-CC-Api-Key": self.api_key,
                        "X-CC-Version": "2018-03-22",
                        "Content-Type": "application/json",
                    },
                    json={
                        "name": "Pry API Access",
                        "description": description or "Pry scraping API credit",
                        "local_price": {"amount": str(amount_usd), "currency": "USD"},
                        "pricing_type": "fixed_price",
                        "metadata": metadata or {},
                    },
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                return {
                    "provider": self.name,
                    "charge_id": data["id"],
                    "url": data["hosted_url"],
                    "status": data["timeline"][-1]["status"],
                    "addresses": {c["code"]: c["address"] for c in data.get("addresses", [])},
                    "expires_at": data.get("expires_at"),
                }
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            raise CryptoPaymentError(f"Coinbase charge creation failed: {e}") from e

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self.webhook_secret:
            return False
        expected = hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def check_status(self, charge_id: str) -> dict[str, Any]:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._base_url}/charges/{charge_id}",
                    headers={
                        "X-CC-Api-Key": self.api_key,
                        "X-CC-Version": "2018-03-22",
                    },
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                return {
                    "charge_id": charge_id,
                    "status": data["timeline"][-1]["status"],
                    "payments": data.get("payments", []),
                }
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(e), "handler": "CoinbaseCommerceProvider.check_status"},
            )
            return {"charge_id": charge_id, "status": "error", "error": str(e)}


class NowPaymentsProvider(CryptoPaymentProvider):
    """NowPayments integration (150+ coins)."""

    name = "nowpayments"

    def __init__(self, api_key: str = "", ipn_secret: str = ""):
        self.api_key = api_key
        self.ipn_secret = ipn_secret
        self._base_url = "https://api.nowpayments.io/v1"

    async def create_charge(
        self,
        amount_usd: float,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise CryptoPaymentError("NowPayments API key not configured")
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/invoice",
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "price_amount": amount_usd,
                        "price_currency": "usd",
                        "pay_currency": metadata.get("currency", "btc") if metadata else "btc",
                        "order_id": metadata.get("order_id", "") if metadata else "",
                        "order_description": description or "Pry API credit",
                        "ipn_callback_url": metadata.get("callback_url", "") if metadata else "",
                        "success_url": metadata.get("success_url", "") if metadata else "",
                        "cancel_url": metadata.get("cancel_url", "") if metadata else "",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "provider": self.name,
                    "charge_id": data["id"],
                    "url": data["invoice_url"],
                    "status": "waiting",
                    "pay_currency": data.get("pay_currency", "btc"),
                    "pay_address": data.get("pay_address", ""),
                    "pay_amount": data.get("pay_amount", 0),
                    "expires_at": data.get("created_at"),
                }
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            raise CryptoPaymentError(f"NowPayments invoice creation failed: {e}") from e

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self.ipn_secret:
            return False
        expected = hmac.new(self.ipn_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def check_status(self, charge_id: str) -> dict[str, Any]:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._base_url}/payment/{charge_id}",
                    headers={"x-api-key": self.api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                return {"charge_id": charge_id, "status": data.get("payment_status", "unknown")}
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(e), "handler": "NowPaymentsProvider.check_status"},
            )
            return {"charge_id": charge_id, "status": "error", "error": str(e)}


class BTCPayProvider(CryptoPaymentProvider):
    """BTCPay Server integration (self-hosted option)."""

    name = "btcpay"

    def __init__(
        self, base_url: str = "", api_key: str = "", store_id: str = "", verify_ssl: bool = True
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.store_id = store_id
        self.verify_ssl = verify_ssl

    async def create_charge(
        self,
        amount_usd: float,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not (self.base_url and self.api_key):
            raise CryptoPaymentError("BTCPay Server not configured")
        try:
            import httpx

            async with httpx.AsyncClient(verify=self.verify_ssl) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/stores/{self.store_id}/invoices",
                    headers={
                        "Authorization": f"token {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "amount": amount_usd,
                        "currency": "USD",
                        "metadata": {
                            "orderId": metadata.get("order_id", "") if metadata else "",
                            "description": description or "Pry API credit",
                            **(metadata or {}),
                        },
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "provider": self.name,
                    "charge_id": data["id"],
                    "url": data["checkoutLink"],
                    "status": data.get("status", "New"),
                    "expires_at": data.get("expirationTime"),
                }
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            raise CryptoPaymentError(f"BTCPay invoice creation failed: {e}") from e

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self.api_key:
            return False
        expected = hmac.new(self.api_key.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def check_status(self, charge_id: str) -> dict[str, Any]:
        try:
            import httpx

            async with httpx.AsyncClient(verify=self.verify_ssl) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/stores/{self.store_id}/invoices/{charge_id}",
                    headers={"Authorization": f"token {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return {"charge_id": charge_id, "status": data.get("status", "unknown")}
        except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(e), "handler": "BTCPayProvider.check_status"},
            )
            return {"charge_id": charge_id, "status": "error", "error": str(e)}


class CryptoPaymentRouter:
    """Routes crypto payments across providers with automatic failover."""

    def __init__(self) -> None:
        self._providers: list[CryptoPaymentProvider] = []
        self._load_providers()

    def _load_providers(self) -> None:
        """Load configured providers from environment."""
        import os

        cb_key = os.getenv("PRY_COINBASE_COMMERCE_API_KEY", "")
        if cb_key:
            self._providers.append(
                CoinbaseCommerceProvider(
                    api_key=cb_key,
                    webhook_secret=os.getenv("PRY_COINBASE_COMMERCE_WEBHOOK_SECRET", ""),
                )
            )

        np_key = os.getenv("PRY_NOWPAYMENTS_API_KEY", "")
        if np_key:
            self._providers.append(
                NowPaymentsProvider(
                    api_key=np_key,
                    ipn_secret=os.getenv("PRY_NOWPAYMENTS_IPN_SECRET", ""),
                )
            )

        btcpay_url = os.getenv("PRY_BTCPAY_URL", "")
        btcpay_key = os.getenv("PRY_BTCPAY_API_KEY", "")
        if btcpay_url and btcpay_key:
            self._providers.append(
                BTCPayProvider(
                    base_url=btcpay_url,
                    api_key=btcpay_key,
                    store_id=os.getenv("PRY_BTCPAY_STORE_ID", ""),
                )
            )

    async def create_charge(
        self,
        amount_usd: float,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a charge, falling back across providers."""
        errors: list[str] = []
        for provider in self._providers:
            try:
                return await provider.create_charge(amount_usd, description, metadata)
            except CryptoPaymentError as e:
                errors.append(f"{provider.name}: {e}")
                logger.warning(
                    "crypto_provider_failed",
                    extra={
                        "provider": provider.name,
                        "error": str(e),
                    },
                )
                continue
        raise CryptoPaymentError(f"All crypto providers failed: {'; '.join(errors)}")

    @property
    def has_providers(self) -> bool:
        return len(self._providers) > 0


_crypto_router: CryptoPaymentRouter | None = None


def get_crypto_router() -> CryptoPaymentRouter:
    """Get the global crypto payment router."""
    global _crypto_router
    if _crypto_router is None:
        _crypto_router = CryptoPaymentRouter()
    return _crypto_router
