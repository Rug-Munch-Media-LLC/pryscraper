"""In-process and optional disk caching for OFAC SDN entries."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from datasets.legal_docs.sanctions.transport import _fetch_entries_network

logger = logging.getLogger(__name__)
_TTL_SECONDS_ENV = "PRY_LEGAL_OFAC_TTL_SECONDS"
_CACHE_PATH_ENV = "PRY_LEGAL_OFAC_CACHE_PATH"
_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_ENTRIES_CACHE: list[dict[str, Any]] | None = None
_ENTRIES_CACHE_TS = 0.0


def _ttl_seconds() -> int:
    raw = os.environ.get(_TTL_SECONDS_ENV, str(_DEFAULT_TTL_SECONDS)).strip()
    digits = raw[1:] if raw[:1] in {"+", "-"} else raw
    if not digits.isdecimal():
        return _DEFAULT_TTL_SECONDS
    return max(60, int(raw))


def _cache_path() -> str | None:
    path = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return path or None


def _read_cache_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            disk = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.debug("legal_ofac_cache_read_failed", exc_info=True, extra={"path": path})
        return None
    return disk if isinstance(disk, dict) else None


def _write_cache_file(path: str, entries: list[dict[str, Any]]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "entries": entries}, handle)
    except OSError:
        logger.warning("legal_ofac_cache_disk_write_failed")


async def _load_entries() -> list[dict[str, Any]] | None:
    global _ENTRIES_CACHE, _ENTRIES_CACHE_TS
    now = time.monotonic()
    if _ENTRIES_CACHE is not None and (now - _ENTRIES_CACHE_TS) < _ttl_seconds():
        return _ENTRIES_CACHE
    path = _cache_path()
    if path:
        disk = _read_cache_file(path)
        if disk is not None and isinstance(disk.get("entries"), list):
            fetched_at = float(disk.get("fetched_at") or 0)
            if time.time() - fetched_at < _ttl_seconds():
                _ENTRIES_CACHE = disk["entries"]
                _ENTRIES_CACHE_TS = now
                logger.info("legal_ofac_cache_disk_hit")
                return _ENTRIES_CACHE
        logger.warning("legal_ofac_cache_disk_unreadable")
    entries = await _fetch_entries_network()
    if not entries:
        return _ENTRIES_CACHE
    _ENTRIES_CACHE = entries
    _ENTRIES_CACHE_TS = now
    if path:
        _write_cache_file(path, entries)
    return entries


def reset_cache() -> None:
    """Drop the in-process OFAC entry cache."""
    global _ENTRIES_CACHE, _ENTRIES_CACHE_TS
    _ENTRIES_CACHE = None
    _ENTRIES_CACHE_TS = 0.0
