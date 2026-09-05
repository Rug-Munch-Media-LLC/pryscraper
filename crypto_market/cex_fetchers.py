"""Per-exchange CEX fetchers (free public endpoints).

Each fetcher returns a list of ``{symbol, base, quote}`` dicts for the
exchange's tradable spot markets. Failures are logged and surfaced as
``None`` by :func:`_safe_fetch` so the signals engine never raises.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from crypto_market.cex_common import _fetch_json, _split_symbol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


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
