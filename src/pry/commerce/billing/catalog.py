"""Pry — scrape-credit pack catalog (server-authoritative pricing).

The pack catalog for bulk scrape-credit purchases (see :mod:`pry.commerce.
billing.packs` for the checkout/settle flow). A scrape credit is worth
``SCRAPE_CREDIT_USD`` (USD); packs are sold at a USD price and credit the
balance with ``credits`` scrape credits:
``credits * SCRAPE_CREDIT_USD == price_usd`` (server-authoritative).

Keep pack ids lowercase and stable — they are the machine-readable key an
agent passes to ``POST /v1/billing/purchase``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.scheme import asset_to_atomic

#: Scrape-credit value in USD (matches the ``scrape`` x402 operation price,
#: so one pack credit == one on-demand scrape).
SCRAPE_CREDIT_USD: float = 0.001

#: Starter credits granted on crypto signup (no email).
STARTER_CREDITS_USD: float = 1.0


class PackWalletUnconfigured(Exception):
    """Raised when no real receiving wallet is configured for the pack network.

    Fail-closed: the caller must NOT emit a placeholder payTo. The operator
    must configure a real wallet (env or secret) before accepting pack
    purchases on the resolved network.
    """


class PackNotFound(Exception):
    """Raised for an unknown pack id."""


class Underpayment(Exception):
    """Raised when a pack payment is reported but does not verify / under-pays.

    Carries a ``reason`` so callers can surface an actionable message.
    """

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Pack:
    """A scrape-credit pack with server-authoritative pricing.

    Attributes:
        id: Canonical pack id (``starter``, ``growth``, ``bulk``).
        price_usd: USD list price of the pack (the x402 amount quoted).
        credits: Number of scrape credits granted (``price_usd / SCRAPE_CREDIT_USD``).
        description: Human-readable summary.
    """

    id: str
    price_usd: float
    credits: int
    description: str

    @property
    def credits_usd(self) -> float:
        """USD value of the credits granted (== ``price_usd``)."""
        return round(self.credits * SCRAPE_CREDIT_USD, 6)

    @property
    def amount_atomic(self) -> int:
        """Server-authoritative x402 amount in atomic units for the default asset."""
        return asset_to_atomic(self.price_usd, X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK)


#: Canonical pack catalog.
PACKS: dict[str, Pack] = {
    "starter": Pack(
        id="starter",
        price_usd=5.0,
        credits=5000,
        description="5,000 scrape credits (~500 full pages)",
    ),
    "growth": Pack(
        id="growth",
        price_usd=20.0,
        credits=20000,
        description="20,000 scrape credits (~2,000 full pages)",
    ),
    "bulk": Pack(
        id="bulk",
        price_usd=100.0,
        credits=100000,
        description="100,000 scrape credits (~10,000 full pages)",
    ),
}


def get_pack(pack_id: str) -> Pack:
    """Resolve *pack_id* to a :class:`Pack`.

    Case-insensitive, whitespace-tolerant. Raises :class:`PackNotFound` for
    unknown ids (the route turns this into a 404/400 — never silently default).
    """
    if not pack_id:
        raise PackNotFound("pack id is required")
    pack = PACKS.get(pack_id.strip().lower())
    if pack is None:
        raise PackNotFound(f"unknown pack '{pack_id}'")
    return pack


def list_packs() -> list[dict[str, Any]]:
    """Return the pack catalog (machine-readable, prices in atomic units)."""
    out: list[dict[str, Any]] = []
    for pack in PACKS.values():
        out.append(
            {
                "id": pack.id,
                "price_usd": pack.price_usd,
                "credits": pack.credits,
                "credits_usd": pack.credits_usd,
                "amount_atomic": pack.amount_atomic,
                "description": pack.description,
                "asset": X402_DEFAULT_ASSET,
                "network": X402_DEFAULT_NETWORK,
                "credit_usd": SCRAPE_CREDIT_USD,
            }
        )
    return out


def _pack_amount_atomic(pack_id: str) -> int:
    """Atomic amount for *pack_id* (0 for unknown ids — never raises)."""
    try:
        return get_pack(pack_id).amount_atomic
    except PackNotFound:
        return 0
