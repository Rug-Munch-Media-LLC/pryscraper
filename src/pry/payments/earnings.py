"""Pry — unified earnings tracker (facade).

Aggregates ALL revenue streams into one view. The implementation is split
across focused mixins:

- :class:`pry.payments.earnings_streams.StreamMixin` — stream loaders
  (x402 per-call, pack purchases, subscriptions, Apify actor projections)
- :class:`pry.payments.earnings_compute.ComputeMixin` — earnings computations
  (totals, daily breakdowns, per-stream/per-chain splits, MRR, growth, CSV)
- :class:`pry.payments.earnings_treasury.TreasuryMixin` — on-chain treasury
  balance probes (EVM / Solana / TRON, resilient by design)

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry.payments.analytics import PaymentAnalytics
from pry.payments.earnings_compute import ComputeMixin
from pry.payments.earnings_shared import (
    TIERS_SAFE,  # noqa: F401
    _count_by,  # noqa: F401
    _ensure_aware,  # noqa: F401
    _tiers_safe,  # noqa: F401
)
from pry.payments.earnings_streams import StreamMixin
from pry.payments.earnings_treasury import (
    ETHERSCAN_API,  # noqa: F401
    ETHERSCAN_API_KEY_ENV,  # noqa: F401
    EVM_PUBLIC_RPC,  # noqa: F401
    LAMPORTS,  # noqa: F401
    SOLANA_RPC,  # noqa: F401
    STABLE_ATOMIC,  # noqa: F401
    TREASURY_CACHE_TTL_S,  # noqa: F401
    TREASURY_EVM,  # noqa: F401
    TREASURY_SOLANA,  # noqa: F401
    TREASURY_TIMEOUT_S,  # noqa: F401
    TREASURY_TRON,  # noqa: F401
    TRONGRID_API,  # noqa: F401
    USDC_ETHEREUM,  # noqa: F401
    WEI,  # noqa: F401
    TreasuryMixin,
    _cached,  # noqa: F401
    _store,  # noqa: F401
    _treasury_cache,  # noqa: F401
)


class EarningsTracker(StreamMixin, TreasuryMixin, ComputeMixin):
    """Aggregate earnings across every Pry revenue stream."""

    def __init__(
        self,
        payments_file: str = "",
        settlements_file: str = "",
        analytics: PaymentAnalytics | None = None,
    ):
        self.analytics = analytics or PaymentAnalytics(
            payments_file=payments_file, settlements_file=settlements_file
        )


# Global tracker instance
_tracker: EarningsTracker | None = None


def get_earnings_tracker() -> EarningsTracker:
    """Get the global earnings tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = EarningsTracker()
    return _tracker
