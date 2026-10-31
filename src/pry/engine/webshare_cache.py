"""Pry — on-disk cache for the Webshare proxy pool (JSON, mode 0600).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_PATH = Path(os.getenv("PRY_WEBSHARE_CACHE", "/var/lib/pry/webshare_proxies.json"))


def load() -> dict:
    """Cached payload, or ``{}`` when absent/unreadable."""
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("best-effort fallback", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def save(payload: dict) -> None:
    """Write the payload owner-only; a cache failure never breaks fetching."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
        CACHE_PATH.chmod(0o600)
    except OSError as exc:
        logger.debug("webshare_cache_write_failed", extra={"error": str(exc)[:80]})
