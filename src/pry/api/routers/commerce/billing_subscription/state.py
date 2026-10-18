"""In-process idempotency and subscription renewal state."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

_ACTIVATED: dict[str, dict[str, Any]] = {}
_AUTO_RENEW: dict[str, bool] = {}
_PENDING_TIER: dict[str, str] = {}
#: api_key -> {"new_tier": str, "detail": dict} for an unpaid upgrade invoice.
_TIER_CHANGE_INVOICES: dict[str, dict[str, Any]] = {}
