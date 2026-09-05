"""x402 402-challenge response helpers (split from enforcement.py).

Pure code move — no logic changes (audit E41 split).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import logging
from typing import Any

from pry.payments.x402 import _encode_payment_required_body

logger = logging.getLogger(__name__)

# full acceptance surface; only the header is compacted under this budget.
X402_PAYMENT_HEADER_MAX_BYTES = 12_000


def _compact_payment_required_header(body: dict[str, Any], max_bytes: int) -> str:
    """Return a base64 PAYMENT-REQUIRED payload that fits ``max_bytes``.

    Pass 1 keeps ONE accept per network (stablecoin preferred) — every chain
    stays payable-from-the-header, which is a documented agent-facing
    contract. Pass 1.5 strips the heavy optional discovery metadata
    (``networks`` / ``supported_assets`` tables) from the HEADER copy only:
    the full body — tables included — is still returned as the response
    body and via ``/v1/x402/pricing``, so no information is lost; the
    header just stops paying the byte tax for what the body already says.
    That alone typically frees enough budget to keep EVERY family's
    stablecoin accept on the wire. Pass 2 drops networks from the tail
    only if still over budget. Always keeps at least one accept so the
    challenge stays valid for spec-compliant clients.
    """
    encoded = _encode_payment_required_body(body)
    if len(encoded.encode()) <= max_bytes:
        return encoded
    accepts = body.get("accepts") or []
    by_network: dict[str, dict[str, Any]] = {}
    ordered_networks: list[str] = []
    for a in accepts:
        net = a.get("network", "")
        if net not in by_network:
            by_network[net] = a
            ordered_networks.append(net)
        elif a.get("asset") in ("USDC", "USDT") and by_network[net].get("asset") not in (
            "USDC",
            "USDT",
        ):
            by_network[net] = a
    kept = [by_network[k] for k in ordered_networks]
    trimmed = {**body, "accepts": kept}
    # Pass 1.5 — header-only metadata strip (discovery tables live in the
    # response body and at /v1/x402/pricing; they cost ~10KB per challenge).
    trimmed.pop("networks", None)
    trimmed.pop("supported_assets", None)
    encoded = _encode_payment_required_body(trimmed)
    while kept and len(encoded.encode()) > max_bytes:
        kept = kept[:-1]
        encoded = _encode_payment_required_body({**trimmed, "accepts": kept})
    if not kept:
        # Never emit an empty accepts array — fall back to the first entry.
        kept = accepts[:1]
        encoded = _encode_payment_required_body({**trimmed, "accepts": kept})
    logger.warning(
        "x402_payment_header_compacted",
        extra={
            "accepts_total": len(accepts),
            "accepts_in_header": len(kept),
            "header_bytes": len(encoded.encode()),
        },
    )
    return encoded
