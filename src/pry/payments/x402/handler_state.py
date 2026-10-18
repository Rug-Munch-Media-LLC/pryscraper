"""Pry — X402Handler state management (public facade).

Split into cohesive slices by responsibility:

- ``handler_state_receipts`` — payment records (DB + JSONL audit trail)
- ``handler_state_ledger``   — settlement ledger, idempotency keys, replay index
- ``handler_state_batch``    — per-item batch receipts + settlement status
- ``handler_state_gate``     — ``is_paid`` access gate, atomic recheck, stats
- ``handler_state_hooks``    — verify/settle hook registries

``StateMixin`` composes them so :class:`~pry.payments.x402.handler.X402Handler`
keeps a single mixin. Every public name is re-exported here, so existing
imports from ``pry.payments.x402.handler_state`` are unchanged.
"""

from __future__ import annotations

from pry.payments.x402.handler_state_batch import BatchSettlementRequest, BatchStateMixin
from pry.payments.x402.handler_state_gate import GateMixin
from pry.payments.x402.handler_state_hooks import HooksMixin
from pry.payments.x402.handler_state_ledger import (
    BATCH_ITEM_SEP,
    LedgerMixin,
    batch_item_payment_id,
    batch_reference,
)
from pry.payments.x402.handler_state_receipts import ReceiptsMixin

__all__ = [
    "BATCH_ITEM_SEP",
    "BatchSettlementRequest",
    "StateMixin",
    "batch_item_payment_id",
    "batch_reference",
]


class StateMixin(
    HooksMixin,
    ReceiptsMixin,
    LedgerMixin,
    BatchStateMixin,
    GateMixin,
):
    """Ledger persistence, replay-hardening indexes, hooks and the payment gate."""
