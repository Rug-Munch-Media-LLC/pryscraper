"""Pry — warmed-cookie storage: persist, load and list session cookie files.

All functions take the warmer directory explicitly so tests can redirect it
without touching the package tree (session cookies are credentials: 0600).
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def collect_cookies(storage_cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the cookie fields the warmer persists."""
    return [
        {
            "name": str(c.get("name", "")),
            "value": str(c.get("value", "")),
            "domain": str(c.get("domain", "")),
            "path": str(c.get("path", "/")),
            "expires": c.get("expires", -1),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
        }
        for c in storage_cookies
    ]


def save_warmed(
    warmer_dir: Path,
    cookie_data: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    """Write the warmed-cookie record and return the caller-facing summary."""
    cookie_file = Path(warmer_dir) / f"{session_id}.json"
    cookie_file.write_text(json.dumps(cookie_data, indent=2))
    os.chmod(cookie_file, 0o600)
    return {
        "success": True,
        "session_id": session_id,
        "domain": cookie_data["domain"],
        "cookie_count": len(cookie_data["cookies"]),
        "pages_visited": cookie_data["pages_visited"],
        "expires_at": cookie_data["expires_at"],
    }


def build_cookie_data(
    target_domain: str,
    session_id: str,
    pages: list[str],
    cookies: list[dict[str, Any]],
    user_agent: str,
) -> dict[str, Any]:
    """Assemble the persisted cookie record with a 30-day expiry."""
    return {
        "domain": target_domain,
        "session_id": session_id,
        "warmed_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "pages_visited": pages,
        "cookies": cookies,
        "user_agent": user_agent,
    }


def load_warmed(warmer_dir: Path, session_id: str) -> dict[str, Any] | None:
    """Get warmed cookies for a session (None when missing, stale or corrupt)."""
    cookie_file = Path(warmer_dir) / f"{session_id}.json"
    if not cookie_file.exists():
        return None
    try:
        data = json.loads(cookie_file.read_text())
        expires = datetime.fromisoformat(data["expires_at"])
        if expires < datetime.now(UTC):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return None


def list_warmed(warmer_dir: Path) -> list[dict[str, Any]]:
    """Summarise every stored warmed-cookie session."""
    sessions: list[dict[str, Any]] = []
    for f in Path(warmer_dir).glob("*.json"):
        try:
            data = json.loads(f.read_text())
            sessions.append(
                {
                    "session_id": data["session_id"],
                    "domain": data["domain"],
                    "warmed_at": data["warmed_at"],
                    "expires_at": data["expires_at"],
                    "cookie_count": len(data.get("cookies", [])),
                }
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("cookie_warmer_session_load_failed", extra={"error": str(e)[:160]})
    return sessions
