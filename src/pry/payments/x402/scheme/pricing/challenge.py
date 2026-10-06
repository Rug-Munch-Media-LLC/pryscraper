"""Self-documenting challenge fields for the x402 PaymentRequired body."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK


def build_challenge(
    accepts: list[dict[str, Any]],
    description: str,
    operation: str,
    price_info: dict[str, Any],
) -> dict[str, str]:
    """Build the description/instructions/error fields of a 402 body.

    An AI agent receiving the 402 must understand WHAT to pay, WHERE, and HOW
    without reading docs: ``description`` is human+machine readable,
    ``instructions`` spells out the pay-then-retry flow with a concrete
    example drawn from the first accept, and ``error`` carries the actionable
    message.
    """
    first = accepts[0] if accepts else {}
    first_amount = str(first.get("maxAmountRequired", ""))
    first_asset = str(first.get("asset", X402_DEFAULT_ASSET))
    first_network = str(first.get("network", X402_DEFAULT_NETWORK))
    first_pay_to = str(first.get("payToAddress", "")) or "<configured treasury>"
    return {
        "description": description or price_info.get("description", operation),
        "instructions": (
            f"payment required: send {first_amount} {first_asset} "
            f"(atomic units) to {first_pay_to} on the "
            f"{first_network} network, then retry this request with the "
            f"PAYMENT-SIGNATURE header containing the payment_id and tx_hash. "
            f"See GET /v1/x402/pricing for the full price list and treasuries."
        ),
        "error": (
            f"payment required: send {first_amount} {first_asset} to "
            f"{first_pay_to} on {first_network}"
        ),
    }
