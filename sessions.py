"""Pry — persistent browser session management.
Saves and restores Playwright browser contexts to disk."""
from paths import PRY_DATA_DIR

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

SESSIONS_DIR = PRY_DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    """Get filesystem path for a session's saved state."""
    return SESSIONS_DIR / f"{session_id}.json"


async def save_session(
    session_id: str,
    cookies: list[dict[str, Any]],
    local_storage: dict[str, str] | None = None,
    session_storage: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Save browser session state to disk."""
    data = {
        "session_id": session_id,
        "saved_at": datetime.now(UTC).isoformat(),
        "cookies": cookies,
        "local_storage": local_storage or {},
        "session_storage": session_storage or {},
        "metadata": metadata or {},
    }
    path = _session_path(session_id)
    try:
        path.write_text(json.dumps(data, indent=2))
        logger.info("session_saved", extra={"session_id": session_id, "path": str(path)})
    except OSError:
        logger.exception("session_save_failed", extra={"session_id": session_id})


async def load_session(session_id: str) -> dict[str, Any] | None:
    """Load saved browser session from disk."""
    path = _session_path(session_id)
    if not path.exists():
        logger.info("session_not_found", extra={"session_id": session_id})
        return None
    try:
        data: dict[str, Any] = cast("dict[str, Any]", json.loads(path.read_text()))
        logger.info(
            "session_loaded", extra={"session_id": session_id, "saved_at": data.get("saved_at")}
        )
        return data
    except (json.JSONDecodeError, OSError):
        logger.exception("session_load_failed", extra={"session_id": session_id})
        return None


async def delete_session(session_id: str) -> bool:
    """Delete a saved session."""
    path = _session_path(session_id)
    if path.exists():
        path.unlink()
        logger.info("session_deleted", extra={"session_id": session_id})
        return True
    return False


async def list_sessions() -> list[dict[str, Any]]:
    """List all saved sessions with metadata."""
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            sessions.append(
                {
                    "session_id": data.get("session_id", path.stem),
                    "saved_at": data.get("saved_at", ""),
                    "metadata": data.get("metadata", {}),
                    "cookie_count": len(data.get("cookies", [])),
                    "size_bytes": path.stat().st_size,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


async def cleanup_sessions(max_age_days: int = 30) -> int:
    """Remove sessions older than max_age_days. Returns count removed."""
    now = time.time()
    removed = 0
    for path in SESSIONS_DIR.glob("*.json"):
        age_days = (now - path.stat().st_mtime) / 86400
        if age_days > max_age_days:
            path.unlink()
            removed += 1
    if removed:
        logger.info("session_cleanup", extra={"removed": removed, "max_age_days": max_age_days})
    return removed
