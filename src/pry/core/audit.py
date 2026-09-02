"""Pry — persistent audit log helper (audit item #21).

Security-relevant events (attestation rejections, underpayment rejections,
rate-limit hits, key revocations, admin actions) previously went to
structured stdout logs only. Compliance needs a durable, queryable trail,
so this module writes ``AuditEvent`` rows to the primary DB.

Design constraints:
- **Best-effort, never raises.** An audit failure must never break the
  request path; failures fall back to a structured log line.
- **Cheap.** Short-lived sync session, single insert, no ORM relationship
  loading. Safe to call from sync handlers and from async middleware
  (SQLite: non-blocking enough; Postgres: one short blocking insert on the
  event loop — acceptable for rejection paths, which are not the happy path).
- **Fire-and-forget.** Returns ``None`` always.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def audit_event(event_type: str, *, actor: str = "", path: str = "", **details: object) -> None:
    """Record a security-relevant event in the ``audit_events`` table.

    Best-effort: any failure (missing SQLAlchemy, broken engine, full disk)
    is swallowed and logged structurally instead of raised.
    """
    try:
        from pry.core.db.models import _HAS_SA, AuditEvent
        from pry.core.db.session import session_scope

        if not _HAS_SA:
            raise RuntimeError("sqlalchemy not installed")

        with session_scope() as session:
            session.add(
                AuditEvent(
                    event_type=event_type,
                    actor=actor,
                    path=path,
                    detail=dict(details),
                )
            )
    except Exception:
        logger.warning(
            "audit_event_write_failed",
            extra={
                "event_type": event_type,
                "actor": actor,
                "path": path,
                "detail": dict(details),
            },
            exc_info=True,
        )
