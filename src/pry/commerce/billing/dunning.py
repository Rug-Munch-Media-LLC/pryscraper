"""Pry — dunning for unpaid subscription invoices.

Three retries at **+1 / +3 / +7 days** after the invoice's due timestamp
(``expires_at``; ``created_at`` when absent). Every fired attempt is appended
to ``record['dunning']['events']`` as a structured event and the attempt
number is recorded, so re-running :func:`run_dunning` at the same or an
earlier clock is a no-op — idempotency is per ``(invoice, attempt)``, not
per call.

After the **third** attempt the invoice is suspended and the subscription is
downgraded to the free tier (expiry moved to *now*), with a
``billing_dunning_suspended`` event. Paid / already-suspended invoices are
never touched.

SPDX-License-Identifier: MIT — Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.commerce.billing.subscription_state import (
    _INVOICES,
    _SUBSCRIPTIONS,
    _lock,
    _save_state_locked,
)
from pry.commerce.billing.subscription_time import _parse_iso, _utc_iso

logger = logging.getLogger(__name__)

#: Days after the due timestamp for each retry (attempt 1, 2, 3).
DUNNING_OFFSETS_DAYS: tuple[int, ...] = (1, 3, 7)
#: Invoice states eligible for dunning.
OPEN_STATUSES = frozenset({"pending", "submitted"})
SUSPENDED = "suspended"


def _due(record: dict[str, Any]) -> datetime | None:
    for key in ("expires_at", "created_at"):
        raw = record.get(key)
        if isinstance(raw, str) and raw:
            try:
                due = _parse_iso(raw)
            except ValueError:
                continue
            return due if due.tzinfo is not None else due.replace(tzinfo=UTC)
    return None


def _state(record: dict[str, Any]) -> dict[str, Any]:
    dunning = record.get("dunning")
    if not isinstance(dunning, dict):
        dunning = {"attempts": [], "events": []}
        record["dunning"] = dunning
    dunning.setdefault("attempts", [])
    dunning.setdefault("events", [])
    return dunning


def _fire(record: dict[str, Any], attempt: int, due: datetime, now: datetime) -> bool:
    """Record one attempt; False when it was already fired (idempotent)."""
    state = _state(record)
    if attempt in state["attempts"]:
        return False
    state["attempts"].append(attempt)
    outcome = "suspend" if attempt == len(DUNNING_OFFSETS_DAYS) else "retry"
    event = {
        "event": "billing_dunning",
        "invoice_id": record.get("invoice_id"),
        "attempt": attempt,
        "due_at": _utc_iso(due),
        "fired_at": _utc_iso(now),
        "outcome": outcome,
    }
    state["events"].append(event)
    logger.warning("billing_dunning_attempt", extra=dict(event))
    return True


def _suspend(record: dict[str, Any], now: datetime) -> None:
    api_key = str(record.get("api_key") or "")
    record["status"] = SUSPENDED
    record["suspended_at"] = _utc_iso(now)
    state = _state(record)
    if state.get("state") == SUSPENDED:
        return
    state["state"] = SUSPENDED
    if api_key and api_key in _SUBSCRIPTIONS:
        subscription = _SUBSCRIPTIONS[api_key]
        subscription["tier"] = "free"
        subscription["expires_at"] = _utc_iso(now)
        subscription["suspended_at"] = _utc_iso(now)
    logger.warning(
        "billing_dunning_suspended",
        extra={"invoice_id": record.get("invoice_id"), "api_key": api_key},
    )


def run_dunning(now: datetime | None = None) -> dict[str, Any]:
    """Fire every due retry and suspend invoices past the final attempt."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    fired = 0
    suspended = 0
    with _lock:
        for record in _INVOICES.values():
            if str(record.get("status", "")).lower() not in OPEN_STATUSES:
                continue
            due = _due(record)
            if due is None:
                continue
            for attempt, offset in enumerate(DUNNING_OFFSETS_DAYS, start=1):
                if moment < due + timedelta(days=offset):
                    break
                if _fire(record, attempt, due, moment):
                    fired += 1
            state = _state(record)
            if len(DUNNING_OFFSETS_DAYS) in state["attempts"] and record.get("status") != SUSPENDED:
                _suspend(record, moment)
                suspended += 1
        if fired or suspended:
            _save_state_locked()

    return {
        "ran_at": _utc_iso(moment),
        "attempts_fired": fired,
        "suspended": suspended,
    }
