# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Typed values and the canonical field contract for the Dextools datasource.

NORMALIZED SCHEMA (single source of truth — ``ROW_FIELDS``):

    chain           str   Dextools chain slug from the URL path (e.g. "ether")
    address         str   Contract address that identifies the record on that
                          chain, exactly as published in the source URL path
                          (``/app/<chain>/pair-explorer/<address>``). Never invented.
    symbol          str   Token ticker, only when the page states it
    name            str   Token name, only when the page states it
    price_usd       float USD price, only when the page states it
    liquidity_usd   float USD liquidity, only when the page states it
    volume_24h_usd  float 24h USD volume, only when the page states it
    holders         int   Holder count, only when the page states it
    tax_buy         float Buy tax percent, only when the page states it
    tax_sell        float Sell tax percent, only when the page states it
    socials         list  Social/website URLs found on the page (deduped, ordered)
    source_url      str   The exact URL that produced this row
    fetched_at      str   ISO-8601 UTC timestamp of the fetch

Every field except ``chain``/``address``/``source_url``/``fetched_at`` is
nullable. A value that is not present on the page stays ``None`` — an absent
value is never inferred, estimated or carried over from another row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROW_FIELDS: tuple[str, ...] = (
    "chain",
    "address",
    "symbol",
    "name",
    "price_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "holders",
    "tax_buy",
    "tax_sell",
    "socials",
    "quality",
    "source_url",
    "fetched_at",
)

#: Refusal codes this datasource is allowed to emit. Anything else is a bug.
REFUSAL_CODES: frozenset[str] = frozenset(
    {"blocked.robots", "blocked.captcha", "blocked.measurement", "unavailable"}
)


@dataclass(frozen=True)
class Refusal:
    """A typed refusal. Never a silent empty success."""

    code: str
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.code not in REFUSAL_CODES:
            raise ValueError(f"unknown refusal code: {self.code}")

    def to_dict(self) -> dict[str, Any]:
        """JSON envelope shape shared by the CLI and the MCP tool."""
        return {"error": "refused", "code": self.code, "reason": self.reason, "detail": self.detail}
