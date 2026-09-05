"""Pry — usage metering for the ASGI middleware.

Split out of the former monolithic middleware.py. Queues Usage rows and
flushes to the DB in batches. Never raises: metering must not take the
API down.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any

from pry.core.middleware_common import logger

_usage_queue: list[dict[str, Any]] = []
_USAGE_FLUSH_SIZE = 50


def _record_usage(
    key_record: dict[str, Any],
    *,
    operation: str,
    status: str,
    duration_ms: int,
    ip: str,
) -> None:
    """Queue a Usage row; flush to the DB in batches.

    Never raises: metering must not take the API down. Batching keeps the
    per-request cost at list-append level; the flush happens inline every
    N requests (simple + dependency-free; swap for a background task when
    write volume justifies it).
    """
    try:
        _usage_queue.append(
            {
                "user_id": key_record["user_id"],
                "api_key_id": key_record["key_id"],
                "operation": operation[:64],
                "status": status,
                "duration_ms": duration_ms,
                "ip": ip[:64],
            }
        )
        if len(_usage_queue) >= _USAGE_FLUSH_SIZE:
            _flush_usage()
    except Exception as e:  # noqa: BLE001 - metering must never break serving
        logger.debug("usage_record_failed", extra={"error": str(e)[:80]})


def _flush_usage() -> int:
    """Persist queued usage rows. Returns the number of rows written."""
    if not _usage_queue:
        return 0
    batch, _usage_queue[:] = _usage_queue[:], []
    try:
        from pry.core.db import models as _models
        from pry.core.db.session import get_session

        with get_session() as session:
            for item in batch:
                session.add(_models.Usage(**item))  # type: ignore[union-attr]
            session.commit()
        return len(batch)
    except Exception as e:  # noqa: BLE001 - drop-on-failure keeps API alive
        logger.warning("usage_flush_failed", extra={"error": str(e)[:120], "dropped": len(batch)})
        return 0
