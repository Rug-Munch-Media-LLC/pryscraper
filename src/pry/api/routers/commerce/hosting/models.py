"""Pydantic request models for hosted-Pry routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HostingSignupRequest(BaseModel):
    """Start a hosted-instance signup (returns a 402 payment manifest)."""

    user_email: str = Field(..., description="Account email for the hosted instance")
    plan_tier: str = Field(..., description="Plan tier (pro / team)")


class HostingConfirmRequest(BaseModel):
    """Confirm the on-chain payment for a hosting invoice."""

    tx_hash: str = Field(..., description="On-chain transaction hash / signature")
    network: str = Field("", description="Network the payment was made on")
    asset: str = Field("", description="Asset paid")
    authorization: dict[str, Any] | None = Field(
        None, description="Optional EIP-3009 authorization object"
    )


class HostingVerifyRequest(BaseModel):
    """Verify the signup email for a hosting invoice."""

    code: str = Field(..., description="The 6-char verification code from the email")


class HostingPortalRequest(BaseModel):
    """Request a fresh portal magic-link for a customer email."""

    email: str = Field(..., description="The email used at signup")
