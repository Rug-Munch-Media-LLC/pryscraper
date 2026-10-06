"""Pry — X402Handler state management (extracted from ``handler.py``).

Owns the ledger persistence (DB-first with JSONL audit fallback), the
replay-hardening indexes (consumed txs, settled txs), the hook registries,
the payment gate (``is_paid`` / ``_amount_covers``) and stats reporting.
Mixed into :class:`~pry.payments.x402.handler.X402Handler` as ``StateMixin``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pry.payments.x402 import (
    PAYMENT_VALIDITY_SECONDS,
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_OFFLINE_MODE,
    X402_SELF_FACILITATE,
)
from pry.payments.x402.scheme import (
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    X402_PRICING,
    X402Asset,
    X402Network,
    X402Scheme,
    asset_to_atomic,
    network_verification_status,
    resolve_price_usd,
)

logger = logging.getLogger(__name__)

logger = logging.getLogger("pry.payments.x402.handler")


class StateMixin:
    """Ledger persistence, replay-hardening indexes, hooks and the payment gate.

    Extracted verbatim from ``X402Handler``; the host class supplies the
    shared state initialised in its ``__init__`` (``payments_file``,
    ``settlements_file``, ``_use_db``, ``_loaded``, ``_consumed_txs``,
    ``_settled_txs``, ``_authorized_payments`` and the hook lists).
    """

    wallet: str
    facilitator_url: str
    payments_file: Path
    settlements_file: Path
    _use_db: bool
    _loaded: bool
    _consumed_txs: set[str]
    _settled_txs: dict[str, dict[str, Any]]
    _pre_settle_hooks: list[Any]
    _post_settle_hooks: list[Any]
    _pre_verify_hooks: list[Any]
    _post_verify_hooks: list[Any]
    _on_verify_failure_hooks: list[Any]

    def on_pre_settle(self, hook: Any) -> None:
        """Register a hook executed before settlement. Can abort by returning {"abort": True, "reason": "..."}."""
        self._pre_settle_hooks.append(hook)

    def on_post_settle(self, hook: Any) -> None:
        """Register a hook executed after successful settlement."""
        self._post_settle_hooks.append(hook)

    def on_pre_verify(self, hook: Any) -> None:
        """Register a hook executed before verification. Can abort by returning {"abort": True, "reason": "..."}."""
        self._pre_verify_hooks.append(hook)

    def on_post_verify(self, hook: Any) -> None:
        """Register a hook executed after successful verification."""
        self._post_verify_hooks.append(hook)

    def on_verify_failure(self, hook: Any) -> None:
        """Register a hook executed when verification fails (router error or unverified result)."""
        self._on_verify_failure_hooks.append(hook)

    def _ensure_loaded(self) -> None:
        """Load payment records on first use (idempotent)."""
        if self._loaded:
            return
        self._load_payments()
        self._loaded = True

    def _load_payments(self) -> None:
        self.payments: list[dict[str, Any]] = []
        self._consumed_txs = set()
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import get_payments

                self.payments = get_payments()
                self._consumed_txs = {
                    p["tx_hash"] for p in self.payments if p.get("tx_hash") and p.get("verified")
                }
                return
            except Exception as e:  # noqa: BLE001 — degrade to file mode
                logger.warning("x402_ledger_db_read_failed", extra={"error": str(e)[:160]})
        if self.payments_file.exists():
            try:
                for line in self.payments_file.read_text().splitlines():
                    if line.strip():
                        p = json.loads(line)
                        self.payments.append(p)
                        if p.get("tx_hash") and p.get("verified"):
                            self._consumed_txs.add(p["tx_hash"])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("x402_state_load_failed", extra={"error": str(e)[:160]})

    def _record_payment(self, payment: dict[str, Any]) -> None:
        """Persist a payment record: DB (source of truth) + JSONL (audit trail).

        DB is authoritative when reachable; the file append is best-effort
        and never blocks the payment flow.
        """
        self._ensure_loaded()
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import record_payment

                record_payment(payment)
            except Exception as e:  # noqa: BLE001 — DB write failure degrades to file
                logger.warning("x402_payment_db_record_failed", extra={"error": str(e)[:160]})
        try:
            with open(self.payments_file, "a") as f:
                f.write(json.dumps(payment) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning("x402_payment_record_failed", extra={"error": str(e)})
        self.payments.append(payment)
        if payment.get("tx_hash") and payment.get("verified"):
            self._consumed_txs.add(payment["tx_hash"])

    def refresh(self) -> None:
        """Reload payment records from the audit file.

        Picks up payments recorded by OTHER X402Handler instances (e.g. the
        /v1/x402/pay route creates a fresh handler per request). Call before
        ``is_paid()`` on the gate path so a just-issued payment_id is visible.
        """
        self._load_payments()
        self._loaded = True

    def _payment_caller_key(self, payment_id: str) -> str:
        """Caller key (API key → user) recorded on the payment, if known."""
        pid = str(payment_id or "").strip()
        if not pid:
            return ""
        self._ensure_loaded()
        for p in reversed(self.payments):
            if str(p.get("payment_id") or "") == pid:
                return str(p.get("caller_key") or "")
        return ""

    def _record_settlement(self, settlement: dict[str, Any]) -> None:
        """Persist a settlement: DB (source of truth) + JSONL (audit trail).

        The DB insert is idempotent by the UNIQUE settlement key — a
        concurrent duplicate returns the existing receipt instead of writing
        a second row. Callers index the success path themselves.
        """
        # so the settlement row can be queried by user_id directly.
        settlement.setdefault(
            "user_id", self._payment_caller_key(str(settlement.get("payment_id") or ""))
        )
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import record_settlement

                key = self._settlement_key(settlement)
                if key:
                    record_settlement(settlement, key)
            except Exception as e:  # noqa: BLE001 — degrade to file-only
                logger.warning("x402_settlement_db_record_failed", extra={"error": str(e)[:160]})
        try:
            with open(self.settlements_file, "a") as f:
                f.write(json.dumps(settlement) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning("x402_settlement_record_failed", extra={"error": str(e)})

    def _load_settlements(self) -> None:
        """Rehydrate the settled-tx idempotency index.

        DB-first when available (authoritative across processes); the JSONL
        audit trail is the fallback. Keys are ``tx:{network}:{tx_hash}`` (the
        on-chain payment is globally unique); only *successful* settlements
        are indexed so a failed attempt never blocks a retry.
        """
        self._settled_txs: dict[str, dict[str, Any]] = {}
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import get_settlements

                for rec in get_settlements():
                    if rec.get("success") is True:
                        key = self._settlement_key(rec)
                        if key:
                            self._settled_txs.setdefault(key, rec)
                return
            except Exception as e:  # noqa: BLE001 — degrade to file mode
                logger.warning("x402_settlement_db_read_failed", extra={"error": str(e)[:160]})
        if not self.settlements_file.exists():
            return
        try:
            for line in self.settlements_file.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec.get("success") is True:
                        key = self._settlement_key(rec)
                        if key:
                            self._settled_txs.setdefault(key, rec)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("x402_state_load_failed", extra={"error": str(e)[:160]})

    def _settlement_key(self, rec: dict[str, Any] | None) -> str:
        """Stable idempotency key for a settlement receipt.

        ``tx:{network}:{tx_hash}`` is preferred — a tx_hash is the on-chain
        proof and can only legitimately settle once. Falls back to
        ``pid:{payment_id}`` only when no tx_hash is present so legacy records
        still get idempotency.
        """
        rec = rec or {}
        tx_hash = str(rec.get("tx_hash") or "").strip()
        if tx_hash:
            network = str(rec.get("network") or "").strip()
            return f"tx:{network}:{tx_hash}"
        pid = str(rec.get("payment_id") or "").strip()
        return f"pid:{pid}" if pid else ""

    def _tx_consumed(self, tx_hash: str) -> bool:
        """True when ``tx_hash`` was already recorded as a *verified* payment.

        Replay-hardening (fix #1): a single on-chain tx must not be able to
        mint unlimited payment_ids. If a payer swaps a fresh ``payment_id``
        onto an already-used tx_hash, verify_payment refuses it.
        """
        if not tx_hash:
            return False
        self._ensure_loaded()
        return tx_hash in self._consumed_txs

    def is_paid(self, payment_id: str, caller_key: str = "", operation: str = "") -> bool:
        """Return True only if the payment is verified, unexpired, caller-bound
        and still satisfies the gate for ``operation``.

        Replay hardening: a verified payment_id is usable for
        ``PAYMENT_VALIDITY_SECONDS`` only, and only by the caller it was bound
        to (IP/payer wallet where available). Payments recorded without an
        ``expires_at`` (pre-hardening data) fail closed.

        Cross-operation + amount hardening: when a gate ``operation`` is
        supplied (the enforcement middleware always does), the payment must
        have been purchased for that exact operation AND its recorded
        server-side required amount (atomic units) must still cover that
        operation's CURRENT server-authoritative price. A cheap ``scrape``
        payment can therefore never unlock a more expensive ``crawl`` /
        ``monitor`` / … endpoint, and a payment that under-pays the current
        price (e.g. a price was raised after purchase) is rejected. Overpayment
        is allowed. Payments recorded before this hardening (no
        ``operation``/``required_amount_atomic``) fail closed for a gated
        operation. Callers that do not gate by operation keep the legacy
        verified/unexpired/caller contract.
        """
        now = datetime.now(UTC)
        self._ensure_loaded()
        for p in self.payments:
            if p.get("payment_id") != payment_id or not p.get("verified"):
                continue
            expires_at = p.get("expires_at")
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) <= now:
                        continue  # expired — must pay again
                except ValueError as exc:
                    logger.warning(
                        "payments_exception_swallowed",
                        extra={"error": str(exc), "handler": "StateMixin.is_paid"},
                    )
                    continue  # malformed expiry → fail closed
            else:
                continue  # no expiry recorded → treat as expired (fail closed)
            # If the payment was bound to a caller, only that caller may reuse it.
            stored_caller = p.get("caller_key") or ""
            if stored_caller and (not caller_key or stored_caller != caller_key):
                continue
            if operation:
                # The gate is for a specific operation: the payment must have
                # been purchased for that operation and still cover its price.
                if (p.get("operation") or "") != operation:
                    continue  # cross-operation replay → reject
                if not self._amount_covers(p, operation):
                    continue  # underpayment / price raised → reject
            # Else: legacy caller without a gate operation — the verified /
            # unexpired / caller checks above are sufficient (the middleware
            # always passes ``operation``).
            return True
        return False

    def _amount_covers(self, payment: dict[str, Any], operation: str) -> bool:
        """Server-authoritative atomic recheck for a gated operation.

        Compares the recorded payment amount (atomic units) against the
        operation's CURRENT server price (also atomic units), computed with the
        same ``asset_to_atomic`` conversion used by ``validate_client_amount``
        on the verify path. Overpayment is allowed; underpayment or an
        unknown/garbled price fails closed. No USD float comparisons.
        """
        asset = payment.get("asset") or X402_DEFAULT_ASSET
        network = payment.get("network") or X402_DEFAULT_NETWORK
        required = resolve_price_usd(operation, network=network, asset=asset)
        if required <= 0 or not math.isfinite(float(required)):
            return False  # no authoritative price → fail closed
        try:
            required_atomic = asset_to_atomic(required, asset, network)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "StateMixin._amount_covers"},
            )
            return False  # unquoteable price → fail closed
        raw_paid = payment.get("required_amount_atomic")
        if raw_paid is None:
            return False  # pre-hardening record without atomics → fail closed
        try:
            paid_atomic = int(raw_paid)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "StateMixin._amount_covers"},
            )
            return False  # garbled atomics → fail closed
        return paid_atomic >= required_atomic

    def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        for p in self.payments:
            if p["payment_id"] == payment_id:
                return p
        return None

    def get_stats(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "total_payments": len(self.payments),
            "wallet": self.wallet,
            "facilitator": self.facilitator_url,
            "pricing": X402_PRICING,
            "supported_networks": [n.value for n in X402Network],
            "supported_assets": [a.value for a in X402Asset],
            "supported_schemes": [s.value for s in X402Scheme],
            # Canonical CAIP-2 acceptance surface (multi-asset table).
            "networks": SUPPORTED_NETWORKS,
            "caip2_networks": list(SUPPORTED_ASSETS.keys()),
            "asset_table": SUPPORTED_ASSETS,
            "verification_status": VERIFICATION_STATUS,
            # Per-network verification label: "live" (EVM) vs
            # "scaffolded:needs_facilitator" (Solana/TRON). No fake security —
            # scaffolded chains are never reported as live.
            "verification_status_by_network": {
                network_id: network_verification_status(network_id)
                for network_id in SUPPORTED_ASSETS
            },
            "offline_mode": X402_OFFLINE_MODE,
            "self_hosted": X402_SELF_FACILITATE,
            "payment_validity_seconds": PAYMENT_VALIDITY_SECONDS,
            "default_network": X402_DEFAULT_NETWORK,
            "default_asset": X402_DEFAULT_ASSET,
        }
