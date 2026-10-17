"""GDPR Art. 17 erasure plumbing plus the DB/JSONL sweeps; status comes from deletion_logic."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from pry.compliance.deletion_logic import (  # noqa: F401
    DB_DELETE_SCOPE,
    DB_PSEUDONYMIISE_SCOPE,
    MIN_USER_ID_LENGTH,
    _entry,
    _record_user_id,
    _word_boundary_match,
    process_deletion,
)
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

GDPR_DIR = PRY_DATA_DIR / "gdpr"
GDPR_DIR.mkdir(parents=True, exist_ok=True)
DELETION_DIR = GDPR_DIR / "deletion"
DELETION_DIR.mkdir(exist_ok=True)


async def request_deletion(
    user_id: str, reason: str = "user_request", requested_by: str = "user"
) -> dict[str, Any]:
    request_id = uuid.uuid4().hex[:12]
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    request = {
        "id": request_id,
        "user_id": user_id,
        "user_hash": user_hash,
        "reason": reason,
        "requested_by": requested_by,
        "status": "pending",
        "requested_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "deleted_records": 0,
    }
    try:
        (DELETION_DIR / f"{request_id}.json").write_text(json.dumps(request, indent=2))
        logger.info("deletion_requested", extra={"user_hash": user_hash, "reason": reason})
        return request
    except OSError as e:
        return {"error": str(e)}


async def execute_deletion(request_id: str) -> dict[str, Any]:
    path = DELETION_DIR / f"{request_id}.json"
    if not path.exists():
        return {"error": f"Deletion request not found: {request_id}"}
    try:
        request: dict[str, Any] = json.loads(path.read_text())
        result = process_deletion(request.get("user_id", ""))
        status = result.get("status", "partial")
        request.update(
            status=status,
            deleted_records=result.get("deleted_records", 0),
            pseudonymised_records=result.get("pseudonymised_records", 0),
            unreadable_records=result.get("unreadable_records", 0),
            scanned_roots=result.get("scanned_roots", []),
            stores=result.get("stores", []),
            completed_at=datetime.now(UTC).isoformat() if status == "completed" else None,
        )
        if status != "completed":
            request["note"] = result.get("note", "Erasure not complete")
            logger.error(
                "deletion_not_fulfilled", extra={"request_id": request_id, "status": status}
            )
        path.write_text(json.dumps(request, indent=2))
        return request
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


# ── DB sweeps: personal tables DELETED; financial tables PSEUDONYMISED (Art. 17(3)(b)).
_PSEUDONYMISE = {
    "ledger_entries": {"reference": ""},
    "x402_payment_records": {"user_id": "", "caller_key": "", "record": {}},
    "x402_settlement_records": {"user_id": "", "receipt": {}},
    "referrals": {"user_id": ""},
    "hosting_invoices": {"user_email": "", "payment": {}, "x402_body": {}, "verification_code": ""},
}


def _schema_gap(exc: Exception) -> bool:
    return any(
        m in str(exc).lower()
        for m in ("no such table", "no such column", "does not exist", "undefined table")
    )


def _subject_ids(session: Any, user_id: str) -> list[str]:
    from sqlalchemy import func

    from pry.core.db.models import User

    rows = session.query(User.user_id).filter(func.lower(User.email) == user_id.lower()).all()
    return sorted({user_id} | {str(row[0]) for row in rows if row[0]})


def _pseudonymise(session: Any, store: str, model: Any, ids: list[str]) -> int:
    from sqlalchemy import func

    from pry.core.db.models import ReferralClick, ReferralConversion

    values = dict(_PSEUDONYMISE[store])
    if store != "referrals":
        return int(
            session.query(model)
            .filter(func.lower(model.user_id).in_(ids))
            .update(values, synchronize_session=False)
        )
    clicks = session.query(ReferralClick).filter(func.lower(ReferralClick.user_id).in_(ids))
    affected = int(clicks.update(values, synchronize_session=False))
    click_ids = session.query(ReferralClick.click_id).filter(
        func.lower(ReferralClick.user_id).in_(ids)
    )
    links = session.query(ReferralConversion).filter(ReferralConversion.click_id.in_(click_ids))
    return affected + int(links.update({"notes": ""}, synchronize_session=False))


def _results(model_map: dict[str, Any], ids: list[str], session: Any) -> list[dict[str, Any]]:
    """Per-store savepoints: one stale schema must not hide the other stores."""
    from sqlalchemy import func

    reports: list[dict[str, Any]] = []
    for scope, action in ((DB_DELETE_SCOPE, "deleted"), (DB_PSEUDONYMIISE_SCOPE, "pseudonymised")):
        for store, _, _ in scope:
            model = model_map[store]
            try:
                with session.begin_nested():
                    if action == "deleted":
                        query = session.query(model).filter(func.lower(model.user_id).in_(ids))
                        affected = int(query.count())
                        if affected:
                            query.delete(synchronize_session=False)
                    else:
                        affected = _pseudonymise(session, store, model, ids)
            except Exception as exc:  # noqa: BLE001 - reported per store
                reports.append(
                    _entry(store, action, 0, 0, "absent" if _schema_gap(exc) else "error")
                )
                continue
            reports.append(_entry(store, action, affected))
    return reports


def sweep_database(user_id: str) -> list[dict[str, Any]]:
    from pry.core.db.models import (
        HostingInvoice,
        LedgerEntry,
        ReferralClick,
        ScrapeJob,
        Usage,
        X402PaymentRecord,
        X402SettlementRecord,
    )
    from pry.core.db.session import session_scope

    model_map = {
        "usage": Usage,
        "scrape_jobs": ScrapeJob,
        "ledger_entries": LedgerEntry,
        "x402_payment_records": X402PaymentRecord,
        "referrals": ReferralClick,
        "x402_settlement_records": X402SettlementRecord,
        "hosting_invoices": HostingInvoice,
    }
    try:
        with session_scope() as session:
            ids = [value.lower() for value in _subject_ids(session, user_id)]
            return _results(model_map, ids, session)
    except Exception as exc:  # noqa: BLE001 - surfaced in the manifest, never raised
        state = "absent" if _schema_gap(exc) else "error"
        logger.warning("gdpr_db_sweep_failed", extra={"state": state, "error": str(exc)[:160]})
        return [
            _entry(name, action, 0, 0, state)
            for name, action, _ in DB_DELETE_SCOPE + DB_PSEUDONYMIISE_SCOPE
        ]


def sweep_x402_jsonl(user_id: str) -> dict[str, Any]:
    # Atomic temp+replace. Unparseable lines are kept and counted as unreadable:
    # they may still hold the subject's key, so the sweep is partial, not clean.
    directory, tokens = PRY_DATA_DIR / "x402", {user_id.lower()}
    affected = unreadable = 0
    for name in ("payments.jsonl", "settlements.jsonl"):
        path = directory / name
        if not path.is_file():
            continue
        kept: list[str] = []
        removed = 0
        try:
            for line in path.read_text(errors="replace").splitlines(keepends=True):
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    unreadable += 1
                    kept.append(line)
                    continue
                keys = {str(record.get(k, "")).lower() for k in ("caller_key", "user_id", "actor")}
                if keys & tokens:
                    removed += 1
                else:
                    kept.append(line)
            if removed:
                tmp = path.with_name(f"{name}.tmp")
                tmp.write_text("".join(kept))
                os.replace(tmp, path)
            affected += removed
        except OSError as exc:
            logger.error("gdpr_x402_purge_failed", extra={"file": name, "error": str(exc)[:160]})
            return _entry("x402/jsonl", "deleted", affected, unreadable + 1, "error")
    return _entry(
        "x402/jsonl", "deleted", affected, unreadable, "ok" if directory.is_dir() else "absent"
    )
