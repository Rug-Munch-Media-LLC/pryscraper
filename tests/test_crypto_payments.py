# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for crypto payment integration."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from payments.crypto import (
    BTCPayProvider,
    CoinbaseCommerceProvider,
    CryptoPaymentError,
    CryptoPaymentRouter,
    NowPaymentsProvider,
    get_crypto_router,
)


class TestCoinbaseCommerceProvider:
    """Coinbase Commerce payment provider tests."""

    @pytest.mark.asyncio
    async def test_create_charge_success(self) -> None:
        provider = CoinbaseCommerceProvider(api_key="test_key")
        mock_response = httpx.Response(
            200,
            json={
                "data": {
                    "id": "test_charge_123",
                    "hosted_url": "https://commerce.coinbase.com/charges/test",
                    "timeline": [{"status": "NEW"}],
                    "addresses": [],
                    "expires_at": "2026-12-31T23:59:59Z",
                }
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await provider.create_charge(10.0, "Test payment")
        assert result["provider"] == "coinbase_commerce"
        assert result["charge_id"] == "test_charge_123"
        assert "url" in result

    @pytest.mark.asyncio
    async def test_create_charge_no_api_key(self) -> None:
        provider = CoinbaseCommerceProvider(api_key="")
        with pytest.raises(CryptoPaymentError, match="API key not configured"):
            await provider.create_charge(10.0)

    @pytest.mark.asyncio
    async def test_verify_webhook(self) -> None:
        provider = CoinbaseCommerceProvider(api_key="key", webhook_secret="secret")
        payload = b'{"event": "charge:created"}'
        # Valid signature
        import hashlib
        import hmac

        valid_sig = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
        assert provider.verify_webhook(payload, valid_sig) is True
        # Invalid signature
        assert provider.verify_webhook(payload, "invalid") is False

    @pytest.mark.asyncio
    async def test_check_status(self) -> None:
        provider = CoinbaseCommerceProvider(api_key="test_key")
        mock_response = httpx.Response(
            200,
            json={"data": {"timeline": [{"status": "COMPLETED"}]}},
        )
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await provider.check_status("charge_123")
        assert result["status"] == "COMPLETED"


class TestNowPaymentsProvider:
    """NowPayments provider tests."""

    @pytest.mark.asyncio
    async def test_create_invoice_success(self) -> None:
        provider = NowPaymentsProvider(api_key="test_key")
        mock_response = httpx.Response(
            200,
            json={
                "id": "invoice_123",
                "invoice_url": "https://nowpayments.io/invoice/123",
                "pay_currency": "btc",
                "pay_address": "bc1q...",
                "pay_amount": 0.001,
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await provider.create_charge(10.0, "Test", {"currency": "btc"})
        assert result["provider"] == "nowpayments"
        assert result["pay_currency"] == "btc"
        assert "pay_address" in result

    @pytest.mark.asyncio
    async def test_create_invoice_no_api_key(self) -> None:
        provider = NowPaymentsProvider(api_key="")
        with pytest.raises(CryptoPaymentError, match="API key not configured"):
            await provider.create_charge(10.0)


class TestBTCPayProvider:
    """BTCPay Server provider tests."""

    @pytest.mark.asyncio
    async def test_create_invoice_success(self) -> None:
        provider = BTCPayProvider(base_url="https://btcpay.test", api_key="key", store_id="store1")
        mock_response = httpx.Response(
            200,
            json={
                "id": "invoice_123",
                "checkoutLink": "https://btcpay.test/i/invoice_123",
                "status": "New",
                "expirationTime": "2026-12-31T23:59:59Z",
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await provider.create_charge(10.0, "Test")
        assert result["provider"] == "btcpay"
        assert result["charge_id"] == "invoice_123"


class TestCryptoPaymentRouter:
    """Crypto payment router tests."""

    @pytest.mark.asyncio
    async def test_router_fallback(self) -> None:
        """Router should fall back to next provider on failure."""
        with patch.dict(
            "os.environ",
            {
                "PRY_COINBASE_COMMERCE_API_KEY": "cb_key",
                "PRY_NOWPAYMENTS_API_KEY": "np_key",
            },
        ):
            router = CryptoPaymentRouter()
            assert router.has_providers is True
            assert len(router._providers) == 2

    @pytest.mark.asyncio
    async def test_router_no_providers(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            router = CryptoPaymentRouter()
            assert router.has_providers is False

    def test_get_crypto_router_singleton(self) -> None:
        r1 = get_crypto_router()
        r2 = get_crypto_router()
        assert r1 is r2
