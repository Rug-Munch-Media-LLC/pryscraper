"""CEX listing / delisting signal detection — diff engine and public API.

Polls free public exchange market endpoints, diffs the current symbol set
against a persisted snapshot of the last-known symbols, and returns
listing / delisting signals.

Semantics
---------
* Signals are *event-like*: each signal is emitted once, the first time it is
  observed, and the snapshot then advances. Re-running the poll returns ``[]``
  until a new change is observed.
* First run seeds the snapshot and returns ``[]``.
* If a snapshot is older than ``lookback_hours`` (staleness guard), it is
  re-seeded silently instead of diffed — changes that happened outside the
  window cannot be attributed to it, and a missed poll must not produce a
  flood of false delisting signals.
* Failures never raise: an exchange that fails to respond is skipped and its
  snapshot is left untouched (no wipe, no spurious signals).
* Snapshots persist to ``~/.pry/crypto_market/<exchange>.json`` (override the
  directory with ``PRY_CEX_SNAPSHOT_DIR``).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import logging

from crypto_market.cex_announcements import _announcement_signals_binance
from crypto_market.cex_common import (
    DEFAULT_LOOKBACK_HOURS,
    SUPPORTED_EXCHANGES,
    _is_stale,
    _read_snapshot,
    _utc_now,
    _write_snapshot,
)
from crypto_market.cex_fetchers import _safe_fetch

logger = logging.getLogger(__name__)


# ── Diff engine ────────────────────────────────────────────────────────
def _diff_signals(
    exchange: str,
    previous: set[str],
    current: set[str],
    meta: dict[str, dict[str, str]],
    action: str,
    detected_at: str,
) -> list[dict]:
    """Emit one signal per symbol that changed between the two sets.

    ``meta`` must map symbols of the *changed* side to their base/quote
    (current meta for listings, previous meta for delistings).
    """
    changed = current - previous if action == "listing" else previous - current
    signals: list[dict] = []
    for symbol in sorted(changed):
        meta_entry = meta.get(symbol, {})
        signals.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "base": meta_entry.get("base", ""),
                "quote": meta_entry.get("quote", ""),
                "action": action,
                "detected_at_utc": detected_at,
                "source": f"{exchange}_ticker",
            }
        )
    return signals


def _resolve_exchanges(exchanges: list[str] | None) -> list[str]:
    """Validate + normalize the requested exchange names (unknown ones skipped)."""
    if not exchanges:
        return list(SUPPORTED_EXCHANGES)
    resolved: list[str] = []
    for name in exchanges:
        key = str(name).strip().lower()
        if key in SUPPORTED_EXCHANGES and key not in resolved:
            resolved.append(key)
        else:
            logger.warning("cex_unsupported_exchange", extra={"exchange": name})
    return resolved


# ── Public API ─────────────────────────────────────────────────────────
async def get_listing_signals(
    exchanges: list[str] | None = None, lookback_hours: int = 24
) -> list[dict]:
    """Detect newly listed symbols since the last successful poll.

    Args:
        exchanges: Exchange names to poll (default: all supported).
        lookback_hours: Snapshot staleness window. A snapshot older than this
            is re-seeded silently instead of diffed.

    Returns:
        List of signal dicts ``{exchange, symbol, base, quote, action,
        detected_at_utc, source}`` with ``action == "listing"`` (plus any
        Binance announcement news). Empty list on failure or no changes.
        Never raises.
    """
    targets = _resolve_exchanges(exchanges)
    if not targets:
        return []
    results = await asyncio.gather(*(_safe_fetch(exchange) for exchange in targets))
    now_iso = _utc_now()
    signals: list[dict] = []
    for exchange, symbols in zip(targets, results, strict=False):
        if symbols is None:
            continue
        previous_snapshot = _read_snapshot(exchange)
        if previous_snapshot is None or _is_stale(previous_snapshot, lookback_hours):
            if previous_snapshot is None:
                logger.info("cex_snapshot_seeded", extra={"exchange": exchange})
            else:
                logger.info(
                    "cex_snapshot_reseeded",
                    extra={"exchange": exchange, "lookback_hours": lookback_hours},
                )
            _write_snapshot(exchange, symbols)
            continue
        previous = {entry["symbol"] for entry in previous_snapshot.get("symbols", [])}
        current_meta = {entry["symbol"]: entry for entry in symbols}
        signals.extend(
            _diff_signals(exchange, previous, set(current_meta), current_meta, "listing", now_iso)
        )
        # Advance the snapshot so each signal is emitted once.
        _write_snapshot(exchange, symbols)
        if exchange == "binance":
            previous_entries = previous_snapshot.get("symbols", [])
            signals.extend(await _announcement_signals_binance(previous_entries, now_iso))
    return signals


async def get_recent_delistings(exchanges: list[str] | None = None) -> list[dict]:
    """Detect symbols removed since the last successful poll.

    Args:
        exchanges: Exchange names to poll (default: all supported).

    Returns:
        List of signal dicts with ``action == "delisting"`` (ticker-diff
        based). Empty list on failure or no changes. Never raises.
    """
    targets = _resolve_exchanges(exchanges)
    if not targets:
        return []
    results = await asyncio.gather(*(_safe_fetch(exchange) for exchange in targets))
    now_iso = _utc_now()
    signals: list[dict] = []
    for exchange, symbols in zip(targets, results, strict=False):
        if symbols is None:
            continue
        previous_snapshot = _read_snapshot(exchange)
        if previous_snapshot is None or _is_stale(previous_snapshot, DEFAULT_LOOKBACK_HOURS):
            if previous_snapshot is None:
                logger.info("cex_snapshot_seeded", extra={"exchange": exchange})
            else:
                logger.info(
                    "cex_snapshot_reseeded",
                    extra={"exchange": exchange, "lookback_hours": DEFAULT_LOOKBACK_HOURS},
                )
            _write_snapshot(exchange, symbols)
            continue
        previous = {entry["symbol"] for entry in previous_snapshot.get("symbols", [])}
        previous_meta = {entry["symbol"]: entry for entry in previous_snapshot.get("symbols", [])}
        current_meta = {entry["symbol"]: entry for entry in symbols}
        signals.extend(
            _diff_signals(
                exchange, previous, set(current_meta), previous_meta, "delisting", now_iso
            )
        )
        # Advance the snapshot so each signal is emitted once.
        _write_snapshot(exchange, symbols)
    return signals
