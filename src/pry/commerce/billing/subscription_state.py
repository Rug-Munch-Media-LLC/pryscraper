"""Pry — subscription state registries + JSON persistence.

In-memory registries for subscription invoices (keyed by invoice_id) and
active subscriptions (keyed by api_key), guarded by a re-entrant lock, with
optional best-effort JSON persistence at a configurable path
(``PRY_SUBSCRIPTIONS_FILE`` or :func:`set_subscription_store_path`).

Writes are atomic (tmp file + rename); persistence failures are logged,
never raised. This module is intentionally decoupled from the invoice /
verification / activation logic — those modules import the registries and
persistence helpers from here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

#: Env var for the optional JSON persistence file (subscriptions + invoices).
ENV_SUBSCRIPTIONS_FILE: str = "PRY_SUBSCRIPTIONS_FILE"

#: Persistence file format version.
_PERSIST_VERSION: int = 1

#: In-memory invoice registry (keyed by invoice_id).
_INVOICES: dict[str, dict[str, Any]] = {}
#: In-memory subscription registry (keyed by api_key).
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}
#: Explicit store path set via :func:`set_subscription_store_path`.
_configured_store_path: Path | None = None
_lock = threading.RLock()

logger = logging.getLogger(__name__)


def set_subscription_store_path(path: str | Path | None) -> None:
    """Enable/disable JSON persistence of subscriptions + invoices.

    Pass a path to persist state there (atomic writes); pass ``None`` to
    disable persistence and fall back to the ``PRY_SUBSCRIPTIONS_FILE`` env
    var. Best-effort: I/O errors are logged, never raised.
    """
    global _configured_store_path
    _configured_store_path = Path(path) if path else None


def reset_subscription_state() -> None:
    """Clear the in-memory registries (test/ops helper; disk untouched)."""
    with _lock:
        _INVOICES.clear()
        _SUBSCRIPTIONS.clear()


def _store_path() -> Path | None:
    """Resolve the persistence file path, or None when persistence is off."""
    if _configured_store_path is not None:
        return _configured_store_path
    env_path = os.environ.get(ENV_SUBSCRIPTIONS_FILE)
    return Path(env_path) if env_path else None


def _ensure_loaded() -> None:
    """Load persisted state from disk when the registries are empty."""
    with _lock:
        _ensure_loaded_locked()


def _ensure_loaded_locked() -> None:
    """Load persisted state from disk. Callers must hold ``_lock``."""
    path = _store_path()
    if path is None or _SUBSCRIPTIONS or _INVOICES or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable subscription store %s: %s", path, exc)
        return
    if not isinstance(payload, dict) or payload.get("version") != _PERSIST_VERSION:
        logger.warning("Ignoring incompatible subscription store %s", path)
        return
    invoices = payload.get("invoices")
    subscriptions = payload.get("subscriptions")
    if isinstance(invoices, dict):
        _INVOICES.update({str(k): v for k, v in invoices.items() if isinstance(v, dict)})
    if isinstance(subscriptions, dict):
        _SUBSCRIPTIONS.update({str(k): v for k, v in subscriptions.items() if isinstance(v, dict)})


def _register_invoice(record: dict[str, Any]) -> None:
    """Store a new invoice and persist. Callers must NOT hold the lock."""
    with _lock:
        _INVOICES[record["invoice_id"]] = record
        _save_state_locked()


def _save_state_locked() -> None:
    """Best-effort atomic persist of invoices + subscriptions."""
    path = _store_path()
    if path is None:
        return
    payload: dict[str, Any] = {
        "version": _PERSIST_VERSION,
        "invoices": _INVOICES,
        "subscriptions": _SUBSCRIPTIONS,
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.error("Failed to persist subscription store %s: %s", path, exc)
