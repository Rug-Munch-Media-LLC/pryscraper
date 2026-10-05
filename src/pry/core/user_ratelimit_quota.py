"""Pry — database-backed quota persistence for the user rate limiter.

Holds every SQL/session touch the per-user limiter makes: the monthly reset
window, the fail-closed quota read, the per-bucket quota refresh and the
best-effort usage write. The limiter itself (``user_ratelimit``) owns the
token bucket and the allow/deny decisions and calls into this module.

Fail-closed is a contract, not a preference: a DB outage must DENY, never
read as zero usage. See ``load_quota_from_db``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from pry.core.db import Usage
from pry.core.user_ratelimit_types import QuotaUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from pry.core.user_ratelimit import UserBucket

logger = logging.getLogger(__name__)


def _session_scope() -> Callable[[], Any]:
    """Resolve the DB session scope through the limiter module.

    ``pry.core.user_ratelimit.async_session_scope`` is the long-standing
    patch point for tests and fault injection, so the lookup happens at call
    time against that module rather than binding a local copy here — a patch
    applied there must govern the real database access.
    """
    from pry.core import user_ratelimit as _limiter

    return _limiter.async_session_scope


def quota_reset_timestamp() -> float:
    """Timestamp of the next monthly quota reset (1st of next month)."""
    now = datetime.now(UTC)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return next_month.timestamp()


def month_start_timestamp() -> float:
    """Timestamp of the first instant of the current month (UTC)."""
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC).timestamp()


async def load_quota_from_db(api_key_id: str) -> int:
    """Load current month's quota usage from database."""
    try:
        async with _session_scope()() as session:
            from sqlalchemy import func, select

            result = await session.execute(
                select(func.coalesce(func.sum(Usage.cost_usd), 0))
                .where(Usage.api_key_id == api_key_id)
                .where(Usage.created_at >= month_start_timestamp())
            )
            return int(result.scalar() or 0)
    except SQLAlchemyError as e:
        # FAIL-CLOSED. Returning 0 here would read as "this user has used
        # no quota", i.e. an unlimited user, so a database outage would
        # silently disable quota enforcement fleet-wide. Deny instead.
        logger.error(
            "quota_read_failed_denying: %s",
            e,
            extra={"api_key_id": api_key_id},
        )
        raise QuotaUnavailableError(
            "quota state unavailable; denying request rather than assuming zero usage"
        ) from e


async def sync_quota(bucket: UserBucket, api_key_id: str, quota_ttl: float) -> None:
    """Refresh the cached quota for one bucket, fail-closed.

    This is the request-path entry point: the HTTP middleware awaits it
    before ``check()`` so a database outage actually reaches the deny
    branch. It only touches the database when the cached quota is older
    than ``quota_ttl``; a fresh bucket is served from cache (a DB round
    trip per request would make the limiter the slowest thing in the
    request).

    On a read failure the bucket is marked unverified rather than being
    reset to zero — the previous usage total is kept and the bucket is
    denied until a later sync succeeds.
    """
    now = time.time()
    if now - bucket.quota_synced_at <= quota_ttl:
        return
    try:
        bucket.quota_used = await load_quota_from_db(api_key_id)
    except QuotaUnavailableError:
        bucket.quota_unverified = True
    else:
        bucket.quota_unverified = False
        bucket.quota_synced_at = now


async def record_usage(
    api_key_id: str,
    user_id: str,
    operation: str,
    endpoint: str,
    status: str,
    duration_ms: int,
    bytes_in: int,
    bytes_out: int,
    cost_usd: float,
    ip: str = "",
    user_agent: str = "",
    error_message: str = "",
) -> None:
    """Record usage to database for billing/analytics."""
    try:
        async with _session_scope()() as session:
            usage = Usage(
                user_id=user_id,
                api_key_id=api_key_id,
                operation=operation,
                endpoint=endpoint,
                status=status,
                duration_ms=duration_ms,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                cost_usd=cost_usd,
                ip=ip,
                user_agent=user_agent,
                error_message=error_message,
            )
            session.add(usage)
    except (SQLAlchemyError, RuntimeError, OSError) as e:
        # Best-effort contract: usage recording must never break the
        # request. Covers DB driver errors, session-scope failures and
        # I/O errors; programming errors still surface.
        logger.warning("usage_recording_failed: %s", e)
