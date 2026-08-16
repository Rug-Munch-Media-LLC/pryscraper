"""Tests for crypto_market.cex_listings — CEX listing/delisting signals.

Covers snapshot seeding, diff detection (new symbol → listing, removed →
delisting), staleness re-seeding, empty-on-failure, multi-exchange polling,
and the Binance announcement secondary source. All HTTP is mocked with
respx — no live network.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx

import crypto_market.cex_listings as cex

if TYPE_CHECKING:
    from pathlib import Path

BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"
BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers"
OKX_TICKERS = "https://www.okx.com/api/v5/market/tickers"
KUCOIN_ALL = "https://api.kucoin.com/api/v1/market/allTickers"
COINBASE_PRODUCTS = "https://api.exchange.coinbase.com/products"
GATE_PAIRS = "https://api.gateio.ws/api/v4/spot/currency_pairs"
KRAKEN_PAIRS = "https://api.kraken.com/0/public/AssetPairs"
BINANCE_ANNOUNCEMENTS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"


@pytest.fixture(autouse=True)
def _isolated_snapshots(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point snapshots at a tmp dir, disable announcements, clear caches."""
    monkeypatch.setenv("PRY_CEX_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_CEX_ANNOUNCEMENTS", "0")
    cex.reset_caches()


# ── Payload builders ───────────────────────────────────────────────────
def _binance_payload(symbols: list[str]) -> list[dict[str, str]]:
    return [{"symbol": symbol, "price": "1.0"} for symbol in symbols]


def _okx_payload(symbols: list[str]) -> dict[str, Any]:
    return {
        "code": "0",
        "data": [
            {
                "instType": "SPOT",
                "instId": symbol,
                "baseCcy": symbol.split("-")[0],
                "quoteCcy": symbol.split("-")[1],
            }
            for symbol in symbols
        ],
    }


def _snapshot_file(tmp_path: Path, exchange: str) -> Path:
    return tmp_path / f"{exchange}.json"


def _write_raw_snapshot(
    tmp_path, exchange: str, symbols: list[str], updated_hours_ago: int
) -> None:
    """Overwrite a snapshot file directly (bypasses the in-memory cache)."""
    path = _snapshot_file(tmp_path, exchange)
    payload = {
        "version": 1,
        "updated_at": (datetime.now(UTC) - timedelta(hours=updated_hours_ago)).isoformat(),
        "symbols": [{"symbol": s, "base": s, "quote": ""} for s in symbols],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    cex.reset_caches()  # the module caches snapshots in memory


def _read_snapshot_file(tmp_path, exchange: str) -> dict[str, Any]:
    return json.loads(_snapshot_file(tmp_path, exchange).read_text(encoding="utf-8"))


# ── Seeding ────────────────────────────────────────────────────────────
@respx.mock
async def test_first_run_seeds_snapshot_and_returns_empty(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(
        return_value=httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"]))
    )
    signals = await cex.get_listing_signals(exchanges=["binance"])
    assert signals == []
    snapshot = _read_snapshot_file(tmp_path, "binance")
    assert {s["symbol"] for s in snapshot["symbols"]} == {"BTCUSDT", "ETHUSDT"}
    assert snapshot["version"] == 1

    # Second run with the same data → still no signals (idempotent).
    again = await cex.get_listing_signals(exchanges=["binance"])
    assert again == []


# ── Listing detection ──────────────────────────────────────────────────
@respx.mock
async def test_new_symbol_yields_listing_signal(tmp_path) -> None:
    route = respx.get(BINANCE_TICKER)
    route.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT", "DOGEUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT", "DOGEUSDT"])),
    ]
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    signals = await cex.get_listing_signals(exchanges=["binance"])
    assert len(signals) == 1
    signal = signals[0]
    assert signal["exchange"] == "binance"
    assert signal["symbol"] == "DOGEUSDT"
    assert signal["base"] == "DOGE"
    assert signal["quote"] == "USDT"
    assert signal["action"] == "listing"
    assert signal["source"] == "binance_ticker"
    assert signal["detected_at_utc"]

    # Snapshot advanced → no duplicate on the next run.
    assert await cex.get_listing_signals(exchanges=["binance"]) == []


# ── Delisting detection ────────────────────────────────────────────────
@respx.mock
async def test_removed_symbol_yields_delisting_signal(tmp_path) -> None:
    route = respx.get(BINANCE_TICKER)
    route.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT"])),
    ]
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    signals = await cex.get_recent_delistings(exchanges=["binance"])
    assert len(signals) == 1
    signal = signals[0]
    assert signal["exchange"] == "binance"
    assert signal["symbol"] == "ETHUSDT"
    assert signal["base"] == "ETH"  # resolved from the previous snapshot
    assert signal["quote"] == "USDT"
    assert signal["action"] == "delisting"
    assert signal["source"] == "binance_ticker"

    # Snapshot advanced → no duplicate on the next run.
    assert await cex.get_recent_delistings(exchanges=["binance"]) == []


@respx.mock
async def test_delisting_on_first_run_is_empty(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(
        return_value=httpx.Response(200, json=_binance_payload(["BTCUSDT"]))
    )
    assert await cex.get_recent_delistings(exchanges=["binance"]) == []
    assert _snapshot_file(tmp_path, "binance").exists()


# ── Staleness / lookback window ────────────────────────────────────────
@respx.mock
async def test_stale_snapshot_is_reseeded_not_diffed(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(
        return_value=httpx.Response(200, json=_binance_payload(["BTCUSDT"]))
    )
    await cex.get_listing_signals(exchanges=["binance"])  # seed
    # Pretend the snapshot is 48h old and a new symbol appeared meanwhile.
    _write_raw_snapshot(tmp_path, "binance", ["BTCUSDT"], updated_hours_ago=48)
    signals = await cex.get_listing_signals(exchanges=["binance"], lookback_hours=24)
    assert signals == []  # too old to attribute → re-seed silently
    assert {s["symbol"] for s in _read_snapshot_file(tmp_path, "binance")["symbols"]} == {"BTCUSDT"}


@respx.mock
async def test_lookback_hours_controls_staleness(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(
        return_value=httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"]))
    )
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    # Snapshot 2h old, new symbol in the feed.
    _write_raw_snapshot(tmp_path, "binance", ["BTCUSDT"], updated_hours_ago=2)
    signals_strict = await cex.get_listing_signals(exchanges=["binance"], lookback_hours=1)
    assert signals_strict == []  # 2h > 1h window → re-seeded

    _write_raw_snapshot(tmp_path, "binance", ["BTCUSDT"], updated_hours_ago=2)
    signals_wide = await cex.get_listing_signals(exchanges=["binance"], lookback_hours=48)
    assert len(signals_wide) == 1
    assert signals_wide[0]["symbol"] == "ETHUSDT"
    assert signals_wide[0]["action"] == "listing"


# ── Failure behavior ───────────────────────────────────────────────────
@respx.mock
async def test_empty_on_failure(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(return_value=httpx.Response(500, text="boom"))
    assert await cex.get_listing_signals(exchanges=["binance"]) == []
    assert not _snapshot_file(tmp_path, "binance").exists()


@respx.mock
async def test_empty_on_non_json(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(return_value=httpx.Response(200, text="<html>proxy</html>"))
    assert await cex.get_listing_signals(exchanges=["binance"]) == []
    assert not _snapshot_file(tmp_path, "binance").exists()


@respx.mock
async def test_failed_poll_preserves_snapshot(tmp_path) -> None:
    route = respx.get(BINANCE_TICKER)
    route.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(500, text="boom"),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
    ]
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    assert await cex.get_listing_signals(exchanges=["binance"]) == []
    # Snapshot survives the failure untouched (no wipe, no spurious signals).
    assert {s["symbol"] for s in _read_snapshot_file(tmp_path, "binance")["symbols"]} == {
        "BTCUSDT",
        "ETHUSDT",
    }
    # Healthy poll with the same data → still no signals.
    assert await cex.get_listing_signals(exchanges=["binance"]) == []


# ── Multi-exchange ─────────────────────────────────────────────────────
@respx.mock
async def test_multiple_exchanges_concurrent(tmp_path) -> None:
    binance = respx.get(BINANCE_TICKER)
    binance.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "DOGEUSDT"])),
    ]
    okx = respx.get(OKX_TICKERS)
    okx.side_effect = [
        httpx.Response(200, json=_okx_payload(["BTC-USDT"])),
        httpx.Response(200, json=_okx_payload(["BTC-USDT", "SOL-USDT"])),
    ]
    await cex.get_listing_signals(exchanges=["binance", "okx"])  # seed

    signals = await cex.get_listing_signals(exchanges=["binance", "okx"])
    assert {s["symbol"] for s in signals} == {"DOGEUSDT", "SOL-USDT"}
    by_symbol = {s["symbol"]: s for s in signals}
    assert by_symbol["DOGEUSDT"]["exchange"] == "binance"
    assert by_symbol["DOGEUSDT"]["base"] == "DOGE"
    assert by_symbol["SOL-USDT"]["exchange"] == "okx"
    assert by_symbol["SOL-USDT"]["base"] == "SOL"
    assert by_symbol["SOL-USDT"]["quote"] == "USDT"
    assert all(s["action"] == "listing" for s in signals)


@respx.mock
async def test_default_exchanges_polls_all(tmp_path) -> None:
    respx.get(BINANCE_TICKER).mock(return_value=httpx.Response(200, json=[]))
    respx.get(BYBIT_TICKERS).mock(return_value=httpx.Response(200, json={"result": {"list": []}}))
    respx.get(OKX_TICKERS).mock(return_value=httpx.Response(200, json={"code": "0", "data": []}))
    respx.get(KUCOIN_ALL).mock(
        return_value=httpx.Response(200, json={"code": "200000", "data": {"ticker": []}})
    )
    respx.get(COINBASE_PRODUCTS).mock(return_value=httpx.Response(200, json=[]))
    respx.get(GATE_PAIRS).mock(return_value=httpx.Response(200, json=[]))
    respx.get(KRAKEN_PAIRS).mock(return_value=httpx.Response(200, json={"error": [], "result": {}}))

    assert await cex.get_listing_signals() == []
    for exchange in cex.SUPPORTED_EXCHANGES:
        assert _snapshot_file(tmp_path, exchange).exists()


@respx.mock
async def test_unknown_exchange_is_skipped(tmp_path) -> None:
    assert await cex.get_listing_signals(exchanges=["not-an-exchange"]) == []
    assert not _snapshot_file(tmp_path, "not-an-exchange").exists()

    respx.get(BINANCE_TICKER).mock(
        return_value=httpx.Response(200, json=_binance_payload(["BTCUSDT"]))
    )
    signals = await cex.get_listing_signals(exchanges=["binance", "bogus"])
    assert signals == []
    assert _snapshot_file(tmp_path, "binance").exists()


# ── Announcement secondary source ──────────────────────────────────────
@respx.mock
async def test_announcement_listing_signal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_CEX_ANNOUNCEMENTS", "1")
    ticker = respx.get(BINANCE_TICKER)
    ticker.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
    ]
    respx.get(url__startswith=BINANCE_ANNOUNCEMENTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "000000",
                "data": {
                    "catalogs": [],
                    "articles": [
                        {
                            "id": 1,
                            "title": "Binance Will List DEXE (DEXE)",
                            "releaseDate": 1786800000000,
                        }
                    ],
                },
            },
        )
    )
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    signals = await cex.get_listing_signals(exchanges=["binance"])
    assert len(signals) == 1
    signal = signals[0]
    assert signal["symbol"] == "DEXE"
    assert signal["action"] == "listing"
    assert signal["source"] == "binance_announcement"
    assert signal["exchange"] == "binance"
    assert signal["detected_at_utc"]


@respx.mock
async def test_announcement_skips_known_symbols(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An announcement about an already-known symbol is not re-reported."""
    monkeypatch.setenv("PRY_CEX_ANNOUNCEMENTS", "1")
    ticker = respx.get(BINANCE_TICKER)
    ticker.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
    ]
    respx.get(url__startswith=BINANCE_ANNOUNCEMENTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "000000",
                "data": {
                    "catalogs": [],
                    "articles": [
                        {
                            "id": 1,
                            "title": "Binance Will List BTC (BTC)",
                            "releaseDate": 1786800000000,
                        }
                    ],
                },
            },
        )
    )
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    assert await cex.get_listing_signals(exchanges=["binance"]) == []


@respx.mock
async def test_announcement_delisting_signal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Delisting news for a live symbol is reported as an early warning."""
    monkeypatch.setenv("PRY_CEX_ANNOUNCEMENTS", "1")
    ticker = respx.get(BINANCE_TICKER)
    ticker.side_effect = [
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
        httpx.Response(200, json=_binance_payload(["BTCUSDT", "ETHUSDT"])),
    ]
    respx.get(url__startswith=BINANCE_ANNOUNCEMENTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "000000",
                "data": {
                    "catalogs": [],
                    "articles": [
                        {
                            "id": 2,
                            "title": "Binance Will Delist ETHUSDT (ETH)",
                            "releaseDate": 1786800000000,
                        }
                    ],
                },
            },
        )
    )
    await cex.get_listing_signals(exchanges=["binance"])  # seed

    signals = await cex.get_listing_signals(exchanges=["binance"])
    assert len(signals) == 1
    assert signals[0]["symbol"] == "ETHUSDT"  # resolved against the snapshot entry
    assert signals[0]["base"] == "ETH"
    assert signals[0]["quote"] == "USDT"
    assert signals[0]["action"] == "delisting"
    assert signals[0]["source"] == "binance_announcement"
