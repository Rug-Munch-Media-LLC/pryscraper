"""Shared plumbing for CEX listing/delisting signal detection.

Constants, symbol splitting, snapshot persistence, and the HTTP fetch
layer used by the per-exchange fetchers and the diff engine.

Free public endpoints only — no paid keys, no secrets.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from pry.core.paths import PRY_DATA_DIR
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGES: tuple[str, ...] = (
    "binance",
    "bybit",
    "okx",
    "kucoin",
    "coinbase",
    "gate",
    "kraken",
)

DEFAULT_LOOKBACK_HOURS = 24

# ── HTTP / retry tuning ────────────────────────────────────────────────
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.2,
    max_delay=1.0,
    retryable_exceptions=(httpx.HTTPError, json.JSONDecodeError),
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; pry-cex-signals/3.0)"}

# ── Snapshot persistence ───────────────────────────────────────────────
_SNAPSHOT_DIR_ENV = "PRY_CEX_SNAPSHOT_DIR"
_ANNOUNCEMENTS_ENV = "PRY_CEX_ANNOUNCEMENTS"
_SNAPSHOT_VERSION = 1

# In-memory mirror of the persisted snapshots (avoids disk reads on repeat
# polls; always advanced together with the on-disk file).
_snapshot_cache: dict[str, dict[str, Any]] = {}

# Known quote assets — longest match wins when splitting bare symbols such as
# Binance's "BTCUSDT" / "1000SATSUSDT" from the ticker-price payload.
_QUOTE_ASSETS: tuple[str, ...] = (
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "USDP",
    "WBTC",
    "WETH",
    "PAXG",
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "TRX",
    "DOT",
    "LTC",
    "BCH",
    "LINK",
    "AVAX",
    "XLM",
    "ARB",
    "OP",
    "MATIC",
    "TON",
    "SUI",
    "APT",
    "NEAR",
    "ATOM",
    "FIL",
    "INJ",
    "SEI",
    "EUR",
    "GBP",
    "USD",
    "ZUSD",
    "TRY",
    "BRL",
    "RUB",
    "UAH",
    "AED",
    "ARS",
    "AUD",
    "BIDR",
    "BYN",
    "COP",
    "CZK",
    "GYEN",
    "HKD",
    "IDRT",
    "ILS",
    "INR",
    "JPY",
    "KRW",
    "KZT",
    "MXN",
    "NGN",
    "NOK",
    "NZD",
    "PEN",
    "PHP",
    "PLN",
    "RON",
    "SAR",
    "SEK",
    "SGD",
    "THB",
    "VAI",
    "VES",
    "VND",
    "ZAR",
)
_SORTED_QUOTE_ASSETS: tuple[str, ...] = tuple(sorted(_QUOTE_ASSETS, key=len, reverse=True))


# ── Time helpers ───────────────────────────────────────────────────────
def _utc_now() -> str:
    """ISO-8601 UTC timestamp used for ``detected_at_utc``."""
    return datetime.now(UTC).isoformat()


# ── Snapshot persistence ───────────────────────────────────────────────
def _snapshot_dir() -> Path:
    """Directory holding ``<exchange>.json`` snapshots (default ``~/.pry/crypto_market``)."""
    override = os.environ.get(_SNAPSHOT_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return PRY_DATA_DIR / "crypto_market"


def _snapshot_path(exchange: str) -> Path:
    return _snapshot_dir() / f"{exchange}.json"


def reset_caches() -> None:
    """Drop the in-memory snapshot cache (used by tests and admin tooling)."""
    _snapshot_cache.clear()


def _read_snapshot(exchange: str) -> dict[str, Any] | None:
    """Load the persisted snapshot for an exchange, or ``None`` if missing/corrupt."""
    cached = _snapshot_cache.get(exchange)
    if cached is not None:
        return cached
    path = _snapshot_path(exchange)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    _snapshot_cache[exchange] = payload
    return payload


def _write_snapshot(exchange: str, symbols: list[dict[str, str]]) -> None:
    """Persist the current symbol set atomically (tmp file + rename)."""
    directory = _snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(exchange)
    payload: dict[str, Any] = {
        "version": _SNAPSHOT_VERSION,
        "updated_at": _utc_now(),
        "symbols": symbols,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    _snapshot_cache[exchange] = payload


def _is_stale(snapshot: dict[str, Any], lookback_hours: int) -> bool:
    """True when a snapshot is older than the lookback window (→ re-seed)."""
    updated = snapshot.get("updated_at")
    if not updated:
        return True
    try:
        timestamp = datetime.fromisoformat(str(updated))
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    window = timedelta(hours=max(1, int(lookback_hours)))
    return (datetime.now(UTC) - timestamp) > window


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _fetch_json(url: str, *, params: dict[str, str] | None = None) -> Any:
    """GET + JSON-decode with timeout and bounded retry/backoff."""

    async def _one() -> Any:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    return await async_retry(_one, config=_RETRY_CONFIG)


# ── Symbol helpers ─────────────────────────────────────────────────────
def _split_symbol(symbol: str) -> tuple[str, str]:
    """Best-effort split of a bare symbol (``BTCUSDT`` → ``("BTC", "USDT")``)."""
    for quote in _SORTED_QUOTE_ASSETS:
        if len(symbol) > len(quote) and symbol.endswith(quote):
            return symbol[: -len(quote)], quote
    return symbol, ""
