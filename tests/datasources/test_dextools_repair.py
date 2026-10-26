# SPDX-License-Identifier: MIT
"""Repair statements and the post-repair mapping (no live ClickHouse)."""

from pry.datasources.dextools_ingest import pair_to_row
from pry.datasources.dextools_repair import DOWN, PAIRS, UP

PAIR = {
    "chain": "arbitrum",
    "pair_address": "arbitrum_0x12a46b5de0c34ade7eee54a2c3310001b303a20e",
    "token_address": "0x25118290E6A5F4139381D072181157035864099D",
    "token_name": "RAIN / USDT 0.3%",
    "token_symbol": "RAIN",
    "liquidity_usd": 2557977.4416,
    "price_usd": 0.01437804455,
    "source_url": "",
}


def test_repair_is_atomic_and_reversible() -> None:
    assert f"EXCHANGE TABLES {PAIRS} AND rugdex.pairs_v2" in UP
    assert f"EXCHANGE TABLES {PAIRS} AND rugdex.pairs_unrepaired_20261026" in DOWN
    assert "row_number() OVER" in " ".join(UP)
    assert "PARTITION BY chain, token_address" in " ".join(UP)


def test_repaired_row_keeps_symbol_price_and_url() -> None:
    row = pair_to_row(PAIR)
    assert row["symbol"] == "RAIN"
    assert row["quality"] == "ok"
    assert row["price_usd"] == 0.01437804455
    assert row["source_url"] == (
        "https://www.dextools.io/app/arbitrum/pair-explorer/"
        "0x12a46b5de0c34ade7eee54a2c3310001b303a20e"
    )
    assert row["address"] == "0x25118290e6a5f4139381d072181157035864099d"


def test_pre_repair_shape_still_derives() -> None:
    legacy = {
        "chain": "arbitrum",
        "token_address": "0xab",
        "token_name": "RAIN / USDT 0.3%",
        "token_symbol": "2557977.4416",
        "liquidity_usd": 1.0,
    }
    row = pair_to_row(legacy)
    assert (row["symbol"], row["quality"]) == ("RAIN", "symbol_from_name")
    # No stated price column and no pair address: NULL, never a reinterpretation.
    assert row["price_usd"] is None
    assert row["source_url"] is None
