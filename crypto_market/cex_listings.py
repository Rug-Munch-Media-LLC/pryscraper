"""CEX listing / delisting signal detection.

Polls free public exchange market endpoints, diffs the current symbol set
against a persisted snapshot of the last-known symbols, and returns
listing / delisting signals.

Free public endpoints only — no paid keys, no secrets:

- binance  https://api.binance.com/api/v3/ticker/price
- bybit    https://api.bybit.com/v5/market/tickers?category=spot
- okx      https://www.okx.com/api/v5/market/tickers?instType=SPOT
- kucoin   https://api.kucoin.com/api/v1/market/allTickers
- coinbase https://api.exchange.coinbase.com/products
- gate     https://api.gateio.ws/api/v4/spot/currency_pairs
- kraken   https://api.kraken.com/0/public/AssetPairs

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
* Binance announcements (https://www.binance.com/bapi/... free CMS feed) are
  polled as a *secondary* signal source — early listing/delisting news before
  the ticker diff can see it. Best-effort; ignored on any failure. Disable
  with the ``PRY_CEX_ANNOUNCEMENTS=0`` env var.
* Snapshots persist to ``~/.pry/crypto_market/<exchange>.json`` (override the
  directory with ``PRY_CEX_SNAPSHOT_DIR``).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from paths import PRY_DATA_DIR
from retry import RetryConfig, async_retry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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

# ── Binance announcement feed (secondary signal source) ───────────────
_BINANCE_ANNOUNCEMENT_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
)
_BINANCE_ANNOUNCEMENT_PARAMS: dict[str, str] = {
    "type": "1",
    "pageNo": "1",
    "pageSize": "20",
    "blockType": "10000022",
    "sortType": "1",
}

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

# Words that look like ticker tokens in announcement titles but are not
# symbols (fallback tokenizer).
_ANNOUNCEMENT_TOKEN_STOP = frozenset(
    {
        "Binance",
        "Will",
        "List",
        "Delist",
        "With",
        "Tag",
        "Applied",
        "Seed",
        "New",
        "Adds",
        "Opens",
        "Trading",
        "For",
        "The",
        "Following",
        "Pairs",
        "And",
        "Starts",
        "Launchpool",
        "Earn",
        "Pre",
        "Market",
        "Official",
        "Support",
        "Update",
        "Mining",
        "Copy",
        "Not",
        "Available",
        "Users",
        "From",
        "Regions",
        "May",
        "Be",
        "Unable",
        "To",
        "Trade",
    }
)


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


# ── Per-exchange fetchers (free public endpoints) ──────────────────────
async def _fetch_binance() -> list[dict[str, str]]:
    data = await _fetch_json("https://api.binance.com/api/v3/ticker/price")
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        base, quote = _split_symbol(symbol)
        out.append({"symbol": symbol, "base": base, "quote": quote})
    return out


async def _fetch_bybit() -> list[dict[str, str]]:
    data = await _fetch_json(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "spot"},
    )
    out: list[dict[str, str]] = []
    tickers = (data or {}).get("result", {}).get("list", []) if isinstance(data, dict) else []
    for item in tickers:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        out.append(
            {
                "symbol": symbol,
                "base": str(item.get("baseCoin") or ""),
                "quote": str(item.get("quoteCoin") or ""),
            }
        )
    return out


async def _fetch_okx() -> list[dict[str, str]]:
    data = await _fetch_json(
        "https://www.okx.com/api/v5/market/tickers",
        params={"instType": "SPOT"},
    )
    out: list[dict[str, str]] = []
    tickers = data.get("data", []) if isinstance(data, dict) else []
    for item in tickers:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("instId") or "").strip()
        if not symbol:
            continue
        out.append(
            {
                "symbol": symbol,
                "base": str(item.get("baseCcy") or ""),
                "quote": str(item.get("quoteCcy") or ""),
            }
        )
    return out


async def _fetch_kucoin() -> list[dict[str, str]]:
    data = await _fetch_json("https://api.kucoin.com/api/v1/market/allTickers")
    out: list[dict[str, str]] = []
    tickers = (data or {}).get("data", {}).get("ticker", []) if isinstance(data, dict) else []
    for item in tickers:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        base, quote = symbol.split("-", 1) if "-" in symbol else ("", "")
        out.append({"symbol": symbol, "base": base, "quote": quote})
    return out


async def _fetch_coinbase() -> list[dict[str, str]]:
    data = await _fetch_json("https://api.exchange.coinbase.com/products")
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "online":
            continue
        symbol = str(item.get("id") or "").strip()
        if not symbol:
            continue
        base = str(item.get("base_currency") or "")
        quote = str(item.get("quote_currency") or "")
        out.append({"symbol": symbol, "base": base, "quote": quote})
    return out


async def _fetch_gate() -> list[dict[str, str]]:
    data = await _fetch_json("https://api.gateio.ws/api/v4/spot/currency_pairs")
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("trade_status") or "") != "tradable":
            continue
        symbol = str(item.get("id") or "").strip()
        if not symbol:
            continue
        out.append(
            {
                "symbol": symbol,
                "base": str(item.get("base") or ""),
                "quote": str(item.get("quote") or ""),
            }
        )
    return out


async def _fetch_kraken() -> list[dict[str, str]]:
    data = await _fetch_json("https://api.kraken.com/0/public/AssetPairs")
    out: list[dict[str, str]] = []
    result = (data or {}).get("result", {}) if isinstance(data, dict) else {}
    if not isinstance(result, dict):
        return out
    for key, item in result.items():
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "online":
            continue
        symbol = str(item.get("altname") or key or "").strip()
        if not symbol:
            continue
        base = str(item.get("base") or "")
        quote = str(item.get("quote") or "")
        wsname = str(item.get("wsname") or "")
        if "/" in wsname:
            base, quote = wsname.split("/", 1)
        out.append({"symbol": symbol, "base": base, "quote": quote})
    return out


_FETCHERS: dict[str, Callable[[], Awaitable[list[dict[str, str]]]]] = {
    "binance": _fetch_binance,
    "bybit": _fetch_bybit,
    "okx": _fetch_okx,
    "kucoin": _fetch_kucoin,
    "coinbase": _fetch_coinbase,
    "gate": _fetch_gate,
    "kraken": _fetch_kraken,
}


async def _safe_fetch(exchange: str) -> list[dict[str, str]] | None:
    """Fetch one exchange; ``None`` on failure (snapshot stays untouched)."""
    try:
        return await _FETCHERS[exchange]()
    except Exception as exc:  # noqa: BLE001 - signals module must never raise
        logger.warning(
            "cex_fetch_failed",
            extra={"exchange": exchange, "error": str(exc)[:120]},
        )
        return None


# ── Announcement parser (secondary signal source) ──────────────────────
def _extract_symbol_tokens(title: str) -> list[str]:
    """Pull ticker-like tokens from an announcement title (best-effort)."""
    tokens: list[str] = []
    for match in re.findall(r"\(([A-Z0-9]{2,12})\)", title):
        token = match.strip()
        if token and token not in tokens:
            tokens.append(token)
    if not tokens:
        for match in re.findall(r"\b[A-Z][A-Z0-9]{1,11}\b", title):
            token = match.strip()
            if token not in _ANNOUNCEMENT_TOKEN_STOP and token not in tokens:
                tokens.append(token)
    return tokens


def _article_time(article: dict[str, Any], fallback: str) -> str:
    release = article.get("releaseDate")
    if isinstance(release, (int, float)) and release > 0:
        try:
            return datetime.fromtimestamp(release / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return fallback
    return fallback


async def _announcement_signals_binance(
    previous_entries: list[dict[str, str]], fallback_dt: str
) -> list[dict[str, str]]:
    """Listing/delisting news from the Binance announcements feed.

    Listing news is emitted only for symbols not already in the snapshot
    (early warning — the ticker may not exist yet). Delisting news is emitted
    only for markets that are in the snapshot (a live market being flagged);
    the announcement token (usually the base asset, e.g. ``ETH``) is resolved
    against the snapshot entry (e.g. ``ETHUSDT``) when possible.
    """
    if os.environ.get(_ANNOUNCEMENTS_ENV, "1") == "0":
        return []
    previous_symbols = {entry["symbol"] for entry in previous_entries}
    previous_bases = {entry.get("base", "") for entry in previous_entries if entry.get("base")}
    try:
        data = await _fetch_json(_BINANCE_ANNOUNCEMENT_URL, params=_BINANCE_ANNOUNCEMENT_PARAMS)
        articles = (
            (data or {}).get("data", {}).get("articles", []) if isinstance(data, dict) else []
        )
    except Exception as exc:  # noqa: BLE001 - secondary source, never raise
        logger.warning("cex_announcement_fetch_failed", extra={"error": str(exc)[:120]})
        return []
    if not isinstance(articles, list):
        return []

    # Dedupe by resolved symbol; a delisting announcement wins over a listing one.
    by_symbol: dict[str, dict[str, str]] = {}
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "")
        lowered = title.lower()
        if "delist" in lowered:
            action = "delisting"
        elif "list" in lowered:
            action = "listing"
        else:
            continue
        detected = _article_time(article, fallback_dt)
        for token in _extract_symbol_tokens(title):
            # Resolve the announcement token against the known market set.
            if token in previous_symbols or token in previous_bases:
                if action == "listing":
                    continue  # already live — old news
                entry = next(
                    (e for e in previous_entries if e["symbol"] == token or e.get("base") == token),
                    None,
                )
                if entry:
                    symbol = entry["symbol"]
                    base = entry.get("base") or token
                    quote = entry.get("quote") or ""
                else:
                    symbol, base, quote = token, token, ""
            else:
                if action == "delisting":
                    continue  # delist news for an unknown market — stale
                symbol, base, quote = token, token, ""
            existing = by_symbol.get(symbol)
            if action == "delisting" or existing is None:
                by_symbol[symbol] = {
                    "exchange": "binance",
                    "symbol": symbol,
                    "base": base,
                    "quote": quote,
                    "action": action,
                    "detected_at_utc": detected,
                    "source": "binance_announcement",
                }

    return list(by_symbol.values())


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
