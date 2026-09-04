"""Pry — X402Handler (verify/settle orchestration).

Owns the handler that creates spec-compliant 402 responses, verifies
payments via the facilitator router, settles them, and tracks payment
records with replay-hardening (expiry + caller binding). Config constants
come from the package root; scheme/facilitator helpers from their modules.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pry.payments.x402 import (
    PAYMENT_VALIDITY_SECONDS,
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_DIR,
    X402_FACILITATOR_URL,
    X402_OFFLINE_MODE,
    X402_SELF_FACILITATE,
    X402_WALLET,
)
from pry.payments.x402.facilitator import FacilitatorRouter, get_facilitator_router
from pry.payments.x402.scheme import (
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    X402_PRICING,
    X402Asset,
    X402Network,
    X402Scheme,
    _encode_payment_required_body,
    asset_to_atomic,
    build_payment_required,
    network_verification_status,
    resolve_price_usd,
    validate_client_amount,
)

logger = logging.getLogger(__name__)

SETTLEMENT_WEBHOOK_URL_ENV = "PRY_SETTLEMENT_WEBHOOK_URL"


async def fire_settlement_webhook(settlement: dict[str, Any]) -> None:
    """Best-effort settlement webhook (audit item #8).

    When ``PRY_SETTLEMENT_WEBHOOK_URL`` is configured (non-empty), POST the
    settlement receipt to that URL via the shared webhook delivery service
    (HMAC-signed, retried, dead-lettered). Empty/unset = disabled — no
    behavior change when unset. Never raises into the payment flow: callers
    wrap this in try/except and log ``x402_settlement_webhook_error``.
    """
    url = os.getenv(SETTLEMENT_WEBHOOK_URL_ENV, "").strip()
    if not url:
        return
    from pry.api.webhook_delivery import WebhookDelivery

    await WebhookDelivery().deliver(url, dict(settlement), "x402.settlement")


class X402Handler:
    """Handle x402 pay-per-request payments per the spec.

    Implements:
    - create_payment_required: build a spec-compliant 402 response
    - verify_payment: check that a payment header is valid (via facilitator)
    - settle_payment: confirm settlement on-chain (via facilitator)
    - require_payment: convenience method that returns a full 402 response
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
        self._load_settlements()

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
        # Ensure the in-memory payment index is loaded before appending —
        # ``verify_payment`` records a payment without a prior ``is_paid`` /
        # ``_tx_consumed`` read, so ``self.payments`` may not be initialized yet.
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

    def _record_settlement(self, settlement: dict[str, Any]) -> None:
        """Persist a settlement: DB (source of truth) + JSONL (audit trail).

        The DB insert is idempotent by the UNIQUE settlement key — a
        concurrent duplicate returns the existing receipt instead of writing
        a second row. Callers index the success path themselves.
        """
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

    def create_payment_required(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
        accepts: list[dict[str, Any]] | None = None,
        preferred_networks: list[str] | None = None,
        preferred_assets: list[str] | None = None,
        multi_asset: bool = False,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Create a spec-compliant x402 payment request.

        Returns: (body_dict, headers_dict)
        - body_dict: the JSON body for the 402 response
        - headers_dict: the HTTP headers to include (PAYMENT-REQUIRED Base64-encoded)

        ``multi_asset=True`` builds options from the canonical
        SUPPORTED_ASSETS table (CAIP-2 network ids + every quotable asset)
        and attaches the supported_assets/networks tables to the body so
        clients see the full multi-chain acceptance surface. The default
        (False) keeps the V1 legacy single-asset shape.
        """
        body = build_payment_required(
            operation,
            resource,
            accepts,
            description,
            preferred_networks=preferred_networks,
            preferred_assets=preferred_assets,
            multi_asset=multi_asset,
        )
        headers = {
            "PAYMENT-REQUIRED": _encode_payment_required_body(body),
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        }
        return body, headers

    async def verify_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
        caller_key: str = "",
        attested_required_atomic: int = 0,
    ) -> dict[str, Any]:
        """Verify a payment via the x402 facilitator router.

        In production this calls POST /verify on the configured facilitator(s).
        Offline mode accepts the payment record directly for self-hosted Pry.

        Server-side pricing is authoritative: when ``operation`` is known the
        configured price is used and any client-supplied ``amount_usd`` is
        ignored. The recorded payment carries an ``expires_at`` and a
        ``caller_key`` so ``is_paid()`` can reject stale/replayed ids.

        ``attested_required_atomic`` (price binding, audit #7): when > 0 the
        attested challenge's SIGNED ``maxAmountRequired`` is forwarded to the
        facilitator as the authoritative required amount for volatile-asset
        comparison. The cross-operation price check
        (``validate_client_amount``) is UNCHANGED — only the source of the
        expected atomic amount for the oracle-priced comparison changes.
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        if operation:
            # Server-authoritative pricing, resolved per (operation, network,
            # asset) and compared in integer atoms. client-supplied
            # ``amount_usd`` is ignored for the required price; underpayment,
            # non-finite and negative amounts are refused. Overpayment allowed.
            ok, reason = validate_client_amount(operation, amount_usd, asset, network=network)
            if not ok:
                logger.warning(
                    "x402_verify_underpayment_rejected",
                    extra={"operation": operation, "reason": reason},
                )
                return {"verified": False, "reason": reason, "settlement": None}
            amount_usd = resolve_price_usd(operation, network=network, asset=asset)
        if amount_usd <= 0:
            # Fail closed: never default to a hardcoded $0.001 price. If no
            # server-authoritative price is resolvable (operation unknown),
            # refuse the payment rather than accepting it at a made-up price.
            amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.0)
            if amount_usd <= 0:
                logger.warning(
                    "x402_verify_pricing_unavailable",
                    extra={"operation": operation, "payment_id": payment_id},
                )
                return {
                    "verified": False,
                    "reason": "unknown operation: pricing unavailable",
                    "settlement": None,
                }

        try:
            result = await self.router.verify(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                amount_usd=amount_usd,
                attested_required_atomic=attested_required_atomic,
            )
        except Exception as e:  # noqa: BLE001 — fail closed on facilitator error
            logger.warning(
                "x402_verify_router_error", extra={"payment_id": payment_id, "error": str(e)}
            )
            return {"verified": False, "reason": f"facilitator error: {e}", "settlement": None}
        # Replay-hardening (fix #1): a tx_hash may only be consumed once. A payer
        # who swaps a fresh payment_id onto an already-verified tx_hash is trying
        # to mint unlimited payment_ids from one on-chain tx — refuse it.
        #
        # The check-then-record sequence is serialized under ``_verify_lock`` so
        # two concurrent requests carrying the same tx_hash cannot both pass the
        # ``_tx_consumed()`` check before either records the payment (double-spend
        # race). The lock is class-level, so it is shared across the fresh handler
        # instances created per request.
        with self._verify_lock:
            if result.get("verified") and self._tx_consumed(tx_hash):
                logger.warning(
                    "x402_verify_tx_replay_rejected",
                    extra={"payment_id": payment_id, "tx_hash": tx_hash},
                )
                return {
                    "verified": False,
                    "reason": "tx_hash already consumed",
                    "settlement": None,
                }
            # Server-authoritative atomic pricing: the verified payment records the
            # operation it was purchased for and the minimum amount (atomic units)
            # the server required at verify time. ``is_paid()`` re-checks both so a
            # cheap payment can never be replayed against a more expensive gated
            # operation, and a payment that under-pays the CURRENT price is refused.
            payment_record = {
                "payment_id": payment_id,
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
                "required_amount_atomic": asset_to_atomic(amount_usd, asset, network),
                "operation": operation,
                "verified": result["verified"],
                "reason": result.get("reason", ""),
                "facilitator": result.get("facilitator", ""),
                "caller_key": caller_key or "",
                "expires_at": (
                    datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)
                ).isoformat(),
                "verified_at": datetime.now(UTC).isoformat(),
            }
            self._record_payment(payment_record)
        return result

    async def settle_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
    ) -> dict[str, Any]:
        """Settle a payment via the facilitator router.

        Returns a settlement receipt (to be Base64-encoded in PAYMENT-RESPONSE header).
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        if operation:
            # Resolve the server-authoritative price per (operation, network,
            # asset); ignore any client-supplied amount for the receipt.
            amount_usd = resolve_price_usd(operation, network=network, asset=asset)
        if amount_usd <= 0:
            amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.001)

        # Idempotency (fix #4): a settled tx must never duplicate ledger
        # entries. If this payment was already settled successfully, return the
        # cached receipt WITHOUT re-rolling the facilitator and WITHOUT appending
        # a second line to settlements.jsonl.
        key = self._settlement_key(
            {"payment_id": payment_id, "tx_hash": tx_hash, "network": network, "asset": asset}
        )
        # Serialize the check-then-settle sequence under _verify_lock to prevent
        # TOCTOU double-settle under concurrent requests (same lock as verify_payment).
        with self._verify_lock:
            # DB-first idempotency: authoritative across processes AND hosts (the
            # in-memory index only sees this process's settles).
            if key and self._use_db:
                try:
                    from pry.payments.x402.ledger_store import settlement_by_key

                    cached = settlement_by_key(key)
                    if cached is not None and cached.get("success") is True:
                        self._settled_txs.setdefault(key, cached)
                        logger.info("x402_settle_idempotent", extra={"settle_key": key})
                        return cached
                except Exception as e:  # noqa: BLE001 — fall through to memory
                    logger.warning(
                        "x402_settle_db_idempotency_failed", extra={"error": str(e)[:160]}
                    )
            if key and key in self._settled_txs:
                logger.info("x402_settle_idempotent", extra={"settle_key": key})
                return self._settled_txs[key]

            settlement = await self.router.settle(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                amount_usd=amount_usd,
            )
            # Enrich the settlement audit record with the identity fields so the
            # JSONL ledger is self-describing (payment_id/tx_hash/network/asset).
            record = dict(settlement or {})
            record.setdefault("payment_id", payment_id)
            record.setdefault("tx_hash", tx_hash)
            record.setdefault("network", network)
            record.setdefault("asset", asset)
            # Only index successful settles so a failed attempt can be retried.
            if record.get("success") is True and key:
                self._settled_txs.setdefault(key, record)

        self._record_settlement(record)
        # Customer notification (audit item #8): fire the settlement webhook
        # ONLY for genuinely new settlements — the idempotent-cache hit path
        # above returns early, so a replayed settle never re-notifies.
        if record.get("success") is True:
            try:
                await fire_settlement_webhook(record)
            except Exception as e:  # noqa: BLE001 — best-effort, never break settle
                logger.warning(
                    "x402_settlement_webhook_error",
                    extra={"payment_id": payment_id, "error": str(e)},
                )
        return settlement

    def require_payment(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        """Build a complete 402 response with proper headers.

        Returns: {"status_code": 402, "headers": {...}, "body": {...}}
        """
        body, headers = self.create_payment_required(operation, resource, description)
        return {
            "status_code": 402,
            "headers": headers,
            "body": body,
        }

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
                except ValueError:
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
        except (TypeError, ValueError):
            return False  # unquoteable price → fail closed
        raw_paid = payment.get("required_amount_atomic")
        if raw_paid is None:
            return False  # pre-hardening record without atomics → fail closed
        try:
            paid_atomic = int(raw_paid)
        except (TypeError, ValueError):
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
