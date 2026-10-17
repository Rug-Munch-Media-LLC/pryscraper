"""Pry — GDPR router: consent, erasure, retention, audit and domain purge."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body
from sqlalchemy import Text, cast, func, text

from pry.core.errors import InvalidRequestError, NotFoundError
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["GDPR"])

# Lazily created (no migration): reads must work on a fresh database too.
_DDL = (
    "CREATE TABLE IF NOT EXISTS domain_blocks (domain VARCHAR(255) PRIMARY KEY, "
    "reason VARCHAR(255) NOT NULL DEFAULT '', created_at VARCHAR(40) NOT NULL DEFAULT '')"
)
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _host(domain: str) -> str:
    """Normalise a URL or hostname to a bare lowercase host, or raise ValueError."""
    value = urlsplit(domain).hostname if "://" in domain else domain.split("/")[0]
    value = (value or "").strip().lower().rstrip(".").split(":")[0]
    if not _HOST_RE.match(value):
        raise ValueError(f"Invalid domain: {domain!r}")
    return value


def is_domain_blocked(domain: str) -> bool:
    """True when the host is blocked. Fails open (logged) if the DB is down."""
    from pry.core.db.session import session_scope

    try:
        host = _host(domain)
        with session_scope() as session:
            session.execute(text(_DDL))
            row = session.execute(
                text("SELECT 1 FROM domain_blocks WHERE domain = :d"), {"d": host}
            ).first()
            return row is not None
    except Exception:
        logger.warning("domain_block_check_failed", exc_info=True)
        return False


def _url_matches(host: str) -> Any:
    def matches(data: dict[str, Any]) -> bool:
        urls = [data.get("url"), (data.get("metadata") or {}).get("url")]
        return any(isinstance(u, str) and urlsplit(u).hostname == host for u in urls)

    return matches


def purge_domain(domain: str, dry_run: bool = True) -> dict[str, Any]:
    """Count (dry run) or purge every stored record whose URL belongs to ``domain``."""
    from pry.compliance import record_store
    from pry.compliance._deletion_scan import _purge_matching_json
    from pry.core.db.models import ScrapeJob, Usage
    from pry.core.db.session import session_scope

    host = _host(domain)
    reports: list[dict[str, Any]] = []
    roots = (("quality", PRY_DATA_DIR / "quality"), ("sessions", PRY_DATA_DIR / "sessions"))
    for store, directory in roots:
        if not directory.is_dir():
            reports.append({"store": store, "affected": 0, "state": "absent"})
        elif dry_run:
            matches = _url_matches(host)
            affected = sum(
                1
                for p in directory.glob("*.json")
                if (data := record_store.load(p)) is not None and matches(data)
            )
            reports.append({"store": store, "affected": affected, "state": "ok"})
        else:
            affected = _purge_matching_json(directory, _url_matches(host))[0]
            reports.append({"store": store, "affected": affected, "state": "ok"})
    with session_scope() as session:
        queries = (
            ("usage", session.query(Usage).filter(func.lower(Usage.endpoint).like(f"%{host}%"))),
            (
                "scrape_jobs",
                session.query(ScrapeJob).filter(cast(ScrapeJob.input_data, Text).like(f"%{host}%")),
            ),
        )
        for store, query in queries:
            affected = int(query.count())
            if affected and not dry_run:
                query.delete(synchronize_session=False)
            reports.append({"store": store, "affected": affected, "state": "ok"})
    return {
        "domain": host,
        "dry_run": dry_run,
        "stores": reports,
        "total_affected": sum(r["affected"] for r in reports),
    }


@router.post("/v1/gdpr/consent", tags=["GDPR"], summary="Record user consent for data processing")
async def record_consent_endpoint(
    user_id: str = Body(...),
    purpose: str = Body("data_collection"),
    consent_given: bool = Body(True),
    ip_address: str = Body(""),
    user_agent: str = Body(""),
) -> dict[str, Any]:
    """Record consent (GDPR Art. 7); consent expires after 365 days."""
    from pry.compliance.gdpr import record_consent

    result = await record_consent(user_id, purpose, consent_given, ip_address, user_agent)
    return {"success": result["success"], "data": result}


@router.get("/v1/gdpr/consent/{user_id}", tags=["GDPR"], summary="Check user consent status")
async def check_consent_endpoint(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    from pry.compliance.gdpr import check_consent

    return {"success": True, "data": check_consent(user_id, purpose)}


@router.post("/v1/gdpr/consent/revoke", tags=["GDPR"], summary="Revoke user consent")
async def revoke_consent_endpoint(
    user_id: str = Body(...), purpose: str = Body("data_collection")
) -> dict[str, Any]:
    from pry.compliance.gdpr import revoke_consent

    return {"success": True, "data": revoke_consent(user_id, purpose)}


@router.post(
    "/v1/gdpr/deletion/request", tags=["GDPR"], summary="Request data deletion (right to erasure)"
)
async def request_deletion_endpoint(
    user_id: str = Body(...), reason: str = Body("user_request")
) -> dict[str, Any]:
    from pry.compliance.gdpr import request_deletion

    result = await request_deletion(user_id, reason)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/gdpr/deletion/execute", tags=["GDPR"], summary="Execute data deletion request")
async def execute_deletion_endpoint(request_id: str = Body(...)) -> dict[str, Any]:
    from pry.compliance.gdpr import execute_deletion

    result = await execute_deletion(request_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/gdpr/retention", tags=["GDPR"], summary="Get data retention policy")
async def get_retention_policy_endpoint() -> dict[str, Any]:
    from pry.compliance.gdpr import get_retention_policy

    return {"success": True, "data": get_retention_policy()}


@router.post(
    "/v1/gdpr/retention/apply",
    tags=["GDPR"],
    summary="Apply retention policy to remove expired data",
)
async def apply_retention() -> dict[str, Any]:
    from pry.compliance.gdpr import apply_retention_policy

    return {"success": True, "data": await apply_retention_policy()}


@router.post(
    "/v1/gdpr/domain/purge",
    tags=["GDPR"],
    summary="Purge all stored data for a domain (dry-run by default)",
)
async def purge_domain_endpoint(
    domain: str = Body(...), dry_run: bool = Body(True)
) -> dict[str, Any]:
    try:
        result = purge_domain(domain, dry_run)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return {"success": True, "data": result}


@router.get("/v1/gdpr/audit", tags=["GDPR"], summary="Get compliance audit log")
async def get_audit_log_endpoint(days_back: int = 7) -> dict[str, Any]:
    from pry.compliance.gdpr import get_audit_log

    events = get_audit_log(days_back)
    return {"success": True, "data": {"events": events, "total": len(events)}}
