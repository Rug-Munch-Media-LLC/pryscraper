"""Product restock / price-drop monitoring for Pry.

Tracks user-configured alerts on retail products (by ASIN or free-text
product name) and resolves the current price through the repo's guarded
``marketplace.amazon`` module — Amazon product pages for ASINs, keyword
search otherwise. A drop alert fires when the current price is at or below
the target price (or, for restock-style alerts without a target, whenever
a price becomes available at all).

The alert store is in-memory by default and can be persisted to JSON via
the ``PRY_DROPS_ALERTS_JSON`` env var (same pattern as the events_data
price-history tracker). All functions are async and never raise — failures
degrade to ``[]`` / ``{}`` / ``{"status": "error"}``.

Contract
--------
* :func:`set_drop_alert` — async, never raises, returns
  ``{"alert_id", "status"}`` (``status`` is ``"created"`` or ``"error"``).
* :func:`check_drop_alerts` — async, never raises, returns a ``list`` of
  ``{alert_id, product, current_price, target_price, triggered,
  delta_pct}`` records (``[]`` when no alerts are configured).
* :func:`list_alerts` — async, never raises, returns the raw alert records.
* :func:`clear_alert` — async, never raises, returns
  ``{"alert_id", "status"}`` (``"cleared"`` or ``"not_found"``).

``delta_pct`` is the percent the current price is above (positive) or
below (negative) the target: ``((current - target) / target) * 100``.
``triggered`` is ``True`` when ``target_price`` is set and ``current_price
<= target_price``; without a target, ``triggered`` is ``False`` and the
alert is a "restock watch" (fires whenever a price appears).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
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
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_ALERTS_JSON_ENV = "PRY_DROPS_ALERTS_JSON"
_MAX_ALERTS = 500

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

# alert_id -> alert record
_ALERTS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()

# Testable price-resolution hook (monkeypatched by tests / ops).
_AMAZON_IMPORT_NAME = "marketplace.amazon"


# ── persistence ────────────────────────────────────────────────────────


def _alerts_path() -> str:
    """Path of the optional JSON persistence file ('' when disabled)."""
    return os.environ.get(_ALERTS_JSON_ENV, "").strip()


def _load_alerts() -> None:
    """Reload tracked alerts from the JSON persistence file (best effort)."""
    path = _alerts_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(entries, dict):
        return
    with _LOCK:
        for alert_id, record in entries.items():
            if not isinstance(record, dict):
                continue
            _ALERTS[str(alert_id)] = record


def _persist_alerts() -> None:
    """Write the alert store to the JSON persistence file (best effort)."""
    path = _alerts_path()
    if not path:
        return
    try:
        with _LOCK:
            payload = {alert_id: dict(record) for alert_id, record in _ALERTS.items()}
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        logger.debug("deals_alerts_persist_failed", exc_info=True)


_load_alerts()


def _reset_alerts() -> None:
    """Drop all in-memory alerts (tests / ops)."""
    with _LOCK:
        _ALERTS.clear()


# ── helpers ────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _is_asin(product: str) -> bool:
    return bool(product and _ASIN_RE.match(product.strip().upper()))


def _looks_like_error_record(product: dict[str, Any]) -> bool:
    """Does a marketplace record carry any usable price data?"""
    if not product:
        return True
    return _to_float(product.get("price")) is None


async def _resolve_price(product: str) -> float | None:
    """Resolve the current price for ``product`` via guarded marketplace.

    Uses ``marketplace.amazon``: ASINs go to ``get_product(asin)``,
    anything else to ``search_products(product, limit=1)`` (first hit).
    Returns ``None`` on missing product, absent module, blocked/empty
    scrape, or malformed data. Never raises.
    """
    text = (product or "").strip()
    if not text:
        return None
    try:
        import importlib

        amazon = importlib.import_module(_AMAZON_IMPORT_NAME)
    except ImportError:
        logger.warning(
            "deals_marketplace_unavailable",
            extra={"module_name": _AMAZON_IMPORT_NAME},
        )
        return None
    try:
        if _is_asin(text):
            record = await amazon.get_product(text)
        else:
            hits = await amazon.search_products(text, limit=1)
            record = hits[0] if hits and isinstance(hits[0], dict) else {}
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "deals_price_resolve_failed",
            extra={"product": text[:120], "error": str(exc)[:160]},
        )
        return None
    if _looks_like_error_record(record):
        return None
    return _to_float(record.get("price"))


def _delta_pct(current: float | None, target: float | None) -> float | None:
    """Percent the current price is above/below the target."""
    if current is None or target is None or target == 0:
        return None
    return round((current - target) / target * 100.0, 2)


def _triggered(current: float | None, target: float | None) -> bool:
    """A price drop fires when current <= target (restock watch: any price)."""
    if current is None:
        return False
    if target is None:
        return True
    return current <= target


# ── public API ─────────────────────────────────────────────────────────


async def set_drop_alert(
    product: str,
    target_price: float | None = None,
    notify_url: str | None = None,
) -> dict[str, Any]:
    """Create a drop alert for a product. Async, never raises.

    Returns ``{"alert_id": <uuid4-hex>, "status": "created"}`` on success,
    ``{"alert_id": "", "status": "error"}`` for a blank product. Persists
    when ``PRY_DROPS_ALERTS_JSON`` is set.
    """
    text = (product or "").strip()
    if not text:
        return {"alert_id": "", "status": "error"}
    target = _to_float(target_price)
    alert_id = uuid.uuid4().hex[:12]
    record: dict[str, Any] = {
        "alert_id": alert_id,
        "product": text,
        "target_price": target,
        "notify_url": (notify_url or "").strip(),
        "created_at": _now_iso(),
        "last_price": None,
        "last_checked_at": None,
    }
    with _LOCK:
        if len(_ALERTS) >= _MAX_ALERTS:
            return {"alert_id": "", "status": "error"}
        _ALERTS[alert_id] = record
    _persist_alerts()
    return {"alert_id": alert_id, "status": "created"}


async def check_drop_alerts() -> list[dict[str, Any]]:
    """Re-resolve every alert's price and report trigger state.

    Returns a ``list`` of ``{alert_id, product, current_price, target_price,
    triggered, delta_pct}`` — newest-first by creation. Prices are resolved
    through the guarded marketplace module; alerts whose price cannot be
    resolved report ``current_price: None`` / ``triggered: False`` and are
    never dropped. Async, never raises.
    """
    with _LOCK:
        snapshot = [dict(record) for record in _ALERTS.values()]
    out: list[dict[str, Any]] = []
    for record in snapshot:
        product = str(record.get("product") or "")
        target = _to_float(record.get("target_price"))
        current = await _resolve_price(product)
        with _LOCK:
            stored = _ALERTS.get(str(record.get("alert_id") or ""))
            if stored is not None:
                stored["last_price"] = current
                stored["last_checked_at"] = _now_iso()
        out.append(
            {
                "alert_id": str(record.get("alert_id") or ""),
                "product": product,
                "current_price": current,
                "target_price": target,
                "triggered": _triggered(current, target),
                "delta_pct": _delta_pct(current, target),
            }
        )
    _persist_alerts()
    # Newest first by insertion (dict preserves insertion order).
    return list(reversed(out))


async def list_alerts() -> list[dict[str, Any]]:
    """Return the raw alert records (newest first). Never raises."""
    with _LOCK:
        records = [dict(record) for record in reversed(_ALERTS.values())]
    return records


async def clear_alert(alert_id: str) -> dict[str, Any]:
    """Remove one alert by id. Async, never raises.

    Returns ``{"alert_id": <id>, "status": "cleared"}`` on success,
    ``{"alert_id": <id>, "status": "not_found"}`` when absent.
    """
    text = (alert_id or "").strip()
    with _LOCK:
        if text not in _ALERTS:
            return {"alert_id": text, "status": "not_found"}
        del _ALERTS[text]
    _persist_alerts()
    return {"alert_id": text, "status": "cleared"}
