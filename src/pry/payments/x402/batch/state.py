"""Shared in-memory and Redis state for x402 batch payments."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import dataclasses
import threading
from typing import Any

from pry.payments.x402 import PAYMENT_VALIDITY_SECONDS

_batch_payments: dict[str, dict[str, Any]] = {}
_batch_lock = threading.Lock()
_consumed_txs: set[str] = set()


@dataclasses.dataclass
class BatchChannel:
    """On-chain batch settlement channel (voucher/claim/refund model)."""

    channel_id: str
    chain_id: str
    depositor: str
    cumulative_claimed: int = 0
    max_claims_per_batch: int = 100
    status: str = "open"


_channels: dict[str, BatchChannel] = {}
_BATCH_KEY_PREFIX = "pry:x402:batch:"
_TX_KEY_PREFIX = "pry:x402:tx:"
_BATCH_TTL_SECONDS = PAYMENT_VALIDITY_SECONDS + 60
_redis_url = ""
_redis_client: Any = None
_redis_failed_at = 0.0
_REDIS_RETRY_SECONDS = 30.0
