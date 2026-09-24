"""Batch settlement channel lifecycle operations."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import hashlib
import time
from typing import Any

from pry.payments.x402.batch import state
from pry.payments.x402.batch.state import BatchChannel


def create_channel(chain_id: str, depositor: str) -> BatchChannel:
    """Open a new on-chain batch settlement channel for a depositor."""
    channel_id = hashlib.sha256(f"{chain_id}:{depositor}:{time.time()}".encode()).hexdigest()[:16]
    channel = BatchChannel(channel_id=channel_id, chain_id=chain_id, depositor=depositor)
    with state._batch_lock:
        state._channels[channel_id] = channel
    return channel


def claim_channel(channel_id: str, amount: int) -> dict[str, Any]:
    """Claim ``amount`` against a channel, respecting the per-batch cap."""
    with state._batch_lock:
        channel = state._channels.get(channel_id)
        if channel is None:
            return {"success": False, "reason": "Channel not found"}
        if channel.status != "open":
            return {"success": False, "reason": f"Channel is {channel.status}"}
        if channel.cumulative_claimed + amount > channel.max_claims_per_batch:
            return {
                "success": False,
                "reason": "Claim exceeds max_claims_per_batch",
                "cumulative_claimed": channel.cumulative_claimed,
                "max_claims_per_batch": channel.max_claims_per_batch,
            }
        channel.cumulative_claimed += amount
        return {
            "success": True,
            "channel_id": channel_id,
            "cumulative_claimed": channel.cumulative_claimed,
            "remaining": channel.max_claims_per_batch - channel.cumulative_claimed,
        }


def refund_channel(channel_id: str) -> dict[str, Any]:
    """Refund a channel: mark it refunded and return the remaining balance."""
    with state._batch_lock:
        channel = state._channels.get(channel_id)
        if channel is None:
            return {"success": False, "reason": "Channel not found"}
        if channel.status != "open":
            return {"success": False, "reason": f"Channel is {channel.status}"}
        channel.status = "refunded"
        remaining = channel.max_claims_per_batch - channel.cumulative_claimed
        return {
            "success": True,
            "channel_id": channel_id,
            "status": channel.status,
            "remaining": remaining,
        }


def get_channel(channel_id: str) -> BatchChannel | None:
    """Return a channel by id, or None."""
    with state._batch_lock:
        return state._channels.get(channel_id)
