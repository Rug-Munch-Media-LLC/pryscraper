"""Database and Redis storage capability detection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from pry.api.capabilities import probes
from pry.core.settings import settings

logger = logging.getLogger(__name__)


def _default_db_port(scheme: str) -> int:
    """Best-effort default TCP port for common DB URL schemes."""
    if "mysql" in scheme:
        return 3306
    if "mssql" in scheme:
        return 1433
    if "oracle" in scheme:
        return 1521
    return 5432


def _db_capability() -> tuple[bool, str]:
    """Best-effort Postgres/DB reachability via a short TCP probe (non-fatal)."""
    url = settings.database_url
    if not url:
        return False, "no database_url configured"
    if url.startswith("sqlite"):
        try:
            path = urlsplit(url).path
            present = bool(path) and Path(path).exists()
            return present, f"sqlite database file {'present' if present else 'missing'}"
        except Exception:
            logger.warning("storage_exception_handler", exc_info=True)
            return False, "sqlite database unavailable"
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        port = parts.port
    except ValueError:
        logger.warning("storage_exception_handler", exc_info=True)
        port = None
    port = port or _default_db_port(parts.scheme)
    if probes._tcp_reachable(host, port):
        return True, f"{parts.scheme} reachable at {host}:{port}"
    return False, f"{parts.scheme} not reachable at {host}:{port}"


def _redis_capability() -> tuple[bool, str]:
    """Best-effort Redis reachability via a short TCP probe (non-fatal)."""
    url = settings.redis_url
    if not url:
        return False, "no redis_url configured"
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        port = parts.port
    except ValueError:
        logger.warning("storage_exception_handler", exc_info=True)
        port = None
    port = port or 6379
    if probes._tcp_reachable(host, port):
        return True, f"redis reachable at {host}:{port}"
    return False, f"redis not reachable at {host}:{port}"


def _storage_capability() -> tuple[bool, str, list[str]]:
    """Detect DB + Redis reachability (lazy, best-effort, non-fatal)."""
    db_ok, db_detail = _db_capability()
    redis_ok, redis_detail = _redis_capability()
    recs: list[str] = []
    if not db_ok:
        recs.append("start Postgres and check PRY_DATABASE_URL")
    if not redis_ok:
        recs.append("start Redis and check PRY_REDIS_URL")
    return db_ok and redis_ok, f"db: {db_detail}; redis: {redis_detail}", recs
