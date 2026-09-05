"""Pry — pack invoice registry + best-effort JSON persistence.

In-memory registry (keyed by invoice_id) backing the pack checkout flow so
confirm is idempotent and survives restarts best-effort — the same contract
as ``billing.subscription``. Persistence is optional: pass a path to
:func:`set_pack_store_path` or set ``PRY_PACKS_STORE_FILE``; I/O errors are
logged, never raised.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

#: Env var for the optional JSON persistence file (pack invoices).
ENV_PACK_STORE_FILE: str = "PRY_PACKS_STORE_FILE"

#: Persistence file format version.
_PERSIST_VERSION: int = 1

logger = logging.getLogger(__name__)

#: In-memory pack invoice registry (keyed by invoice_id).
invoices: dict[str, dict[str, Any]] = {}
#: Registry lock (reentrant — nested acquisition is safe).
lock = threading.RLock()
#: Explicit store path set via :func:`set_pack_store_path`.
_configured_store_path: Path | None = None


def set_pack_store_path(path: str | Path | None) -> None:
    """Enable/disable JSON persistence of pack invoices.

    Pass a path to persist there (atomic writes); ``None`` disables and falls
    back to the ``PRY_PACKS_STORE_FILE`` env var. Best-effort: I/O errors are
    logged, never raised.
    """
    global _configured_store_path
    _configured_store_path = Path(path) if path else None


def reset_pack_state() -> None:
    """Clear the in-memory pack invoice registry (test/ops helper)."""
    with lock:
        invoices.clear()


def _store_path() -> Path | None:
    """Resolve the persistence file path, or None when persistence is off."""
    if _configured_store_path is not None:
        return _configured_store_path
    env_path = os.environ.get(ENV_PACK_STORE_FILE)
    return Path(env_path) if env_path else None


def ensure_loaded() -> None:
    """Load persisted state from disk when the registry is empty."""
    with lock:
        _ensure_loaded_locked()


def _ensure_loaded_locked() -> None:
    """Load persisted state from disk. Callers must hold ``lock``."""
    path = _store_path()
    if path is None or invoices or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable pack store %s: %s", path, exc)
        return
    if not isinstance(payload, dict) or payload.get("version") != _PERSIST_VERSION:
        logger.warning("Ignoring incompatible pack store %s", path)
        return
    stored = payload.get("invoices")
    if isinstance(stored, dict):
        invoices.update({str(k): v for k, v in stored.items() if isinstance(v, dict)})


def register_invoice(record: dict[str, Any]) -> None:
    """Store a new pack invoice and persist. Callers must NOT hold the lock."""
    with lock:
        invoices[record["invoice_id"]] = record
        save_state_locked()


def save_state_locked() -> None:
    """Best-effort atomic persist of pack invoices. Callers must hold ``lock``."""
    path = _store_path()
    if path is None:
        return
    payload: dict[str, Any] = {
        "version": _PERSIST_VERSION,
        "invoices": invoices,
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.error("Failed to persist pack store %s: %s", path, exc)
