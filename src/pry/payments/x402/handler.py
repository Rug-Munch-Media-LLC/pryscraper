"""Pry — X402Handler (verify/settle orchestration).

Owns the handler that creates spec-compliant 402 responses, tracks payment
records with replay-hardening (expiry + caller binding), and delegates
payment verification/settlement to the extracted mixins
(``handler_verify`` / ``handler_settle``). Ledger persistence, replay
hardening and the payment gate live in ``handler_state`` (``StateMixin``);
402 response building in ``handler_response`` (``ResponseMixin``). Config
constants come from the package root; scheme/facilitator helpers from their
modules.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from pry.payments.x402 import (
    X402_DIR,
    X402_FACILITATOR_URL,
    X402_WALLET,
)
from pry.payments.x402.facilitator import FacilitatorRouter, get_facilitator_router
from pry.payments.x402.handler_response import ResponseMixin
from pry.payments.x402.handler_settle import SettleError, SettleMixin
from pry.payments.x402.handler_state import StateMixin
from pry.payments.x402.handler_tracking import (
    SubscriptionManager,
    UsageTracker,
    fire_settlement_webhook,
)
from pry.payments.x402.handler_verify import VerifyError, VerifyMixin

__all__ = [
    "FacilitatorTimeoutError",
    "SettleError",
    "VerifyError",
    "X402Handler",
    "fire_settlement_webhook",
]


class FacilitatorTimeoutError(Exception):
    """Facilitator timed out."""

    def __init__(self, facilitator: str = "", **extra: Any):
        self.facilitator = facilitator
        self.extra = extra
        super().__init__(f"facilitator {facilitator} timed out")


class X402Handler(StateMixin, ResponseMixin, VerifyMixin, SettleMixin):
    """Handle x402 pay-per-request payments per the spec.

    Implements:
    - create_payment_required: build a spec-compliant 402 response
    - verify_payment: check that a payment header is valid (via facilitator)
    - settle_payment: confirm settlement on-chain (via facilitator)
    - require_payment: convenience method that returns a full 402 response

    Verify/settle logic lives in the ``VerifyMixin`` / ``SettleMixin``
    (handler_verify.py / handler_settle.py); ledger persistence, replay
    hardening, hooks and the payment gate in ``StateMixin``
    (handler_state.py); 402 response building in ``ResponseMixin``
    (handler_response.py). This class owns construction and the shared
    class-level ``_verify_lock``.
    """

    # Serializes the check-then-record sequence in ``verify_payment`` so two
    # concurrent requests carrying the same tx_hash cannot both pass the
    # ``_tx_consumed()`` replay check before either records the payment
    # (double-spend race). Class-level so all handler instances share it.
    _verify_lock = threading.Lock()

    def __init__(
        self,
        wallet: str = "",
        facilitator_url: str = "",
        router: FacilitatorRouter | None = None,
        payments_file: str | Path | None = None,
        settlements_file: str | Path | None = None,
    ) -> None:
        self.wallet = wallet or X402_WALLET
        self.facilitator_url = facilitator_url or X402_FACILITATOR_URL
        self.router = router or get_facilitator_router()
        # Overridable audit-log paths (tests inject per-call temp files). When
        # omitted, the canonical package data dir is used so a fresh handler per
        # request shares the same payments/settlements JSONL.
        self.payments_file = Path(payments_file) if payments_file else X402_DIR / "payments.jsonl"
        self.settlements_file = (
            Path(settlements_file) if settlements_file else X402_DIR / "settlements.jsonl"
        )
        # Audit item #2: Postgres is the source of truth when the DB is
        # reachable; the JSONL files remain as an audit-only trail. Adoption
        # rule: explicit ledger files (tests) → file mode; a configured
        # PRY_DATABASE_URL + reachable DB (production) → DB mode; otherwise
        # the legacy file path (dev default).
        from pry.payments.x402.ledger_store import available as _ledger_available

        self._use_db = (
            payments_file is None
            and settlements_file is None
            and bool(os.environ.get("PRY_DATABASE_URL"))
            and _ledger_available()
        )
        # Lazy loading (perf): payment records are only read from the ledger /
        # audit file on first use (``is_paid`` / ``_tx_consumed``), not at
        # construction. A fresh handler per request therefore avoids loading up
        # to 10k records it may never need.
        self._loaded = False
        self._consumed_txs: set[str] = set()
        self._pre_settle_hooks: list = []
        self._post_settle_hooks: list = []
        self._pre_verify_hooks: list = []
        self._post_verify_hooks: list = []
        self._on_verify_failure_hooks: list = []
        self._authorized_payments: dict[str, dict] = {}
        self.subscriptions = SubscriptionManager()
        self.usage = UsageTracker()
        self._load_settlements()
