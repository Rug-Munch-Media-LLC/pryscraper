"""Shared context object for x402 PricingRequired accept construction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AcceptRequest:
    """Request context shared by the default-accepts builders."""

    operation: str
    price_info: dict[str, Any]
    resource_url: str
    description: str = ""
    mime_type: str = "application/json"
    amount_atomic: int = 0
    preferred_networks: list[str] | None = None
    preferred_assets: list[str] | None = None
