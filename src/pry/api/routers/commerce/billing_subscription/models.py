"""Pydantic request models for subscription billing routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubscriptionInvoiceRequest(BaseModel):
    """Create a hosted-pry subscription invoice for a monthly tier."""

    tier: str = Field(..., description="Tier id (pro / team)")
    api_key: str = Field(..., description="API key whose account is subscribed")
    months: int = Field(1, description="Number of months to subscribe (>= 1)")


class SubscriptionConfirmRequest(BaseModel):
    """Report the on-chain payment for a subscription invoice and verify it."""

    tx_hash: str = Field(..., description="On-chain transaction hash / signature")
    network: str = Field("", description="Network the payment was made on")
    asset: str = Field("", description="Asset paid")
    authorization: dict[str, Any] | None = Field(
        None, description="Optional EIP-3009 authorization object"
    )


class SubscriptionCancelRequest(BaseModel):
    """Cancel a subscription (stops auto-renewal, keeps access until period end)."""

    api_key: str = Field(..., description="API key whose subscription is cancelled")


class SubscriptionRenewRequest(BaseModel):
    """Create a renewal invoice for the next subscription period."""

    api_key: str = Field(..., description="API key whose subscription is renewed")
    months: int = Field(1, description="Number of months to renew (>= 1)")


class SubscriptionChangeTierRequest(BaseModel):
    """Change the subscription tier (upgrades prorate; downgrades defer)."""

    api_key: str = Field(..., description="API key whose subscription changes tier")
    new_tier: str = Field(..., description="Target tier id (pro / team)")
