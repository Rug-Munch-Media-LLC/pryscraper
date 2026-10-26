"""Normalization from a captured rendered page; nulls stay null (no fabrication)."""

from __future__ import annotations

from pathlib import Path

from pry.datasources.dextools_normalize import normalize_page
from pry.datasources.dextools_types import ROW_FIELDS

FIXTURE = Path(__file__).parent / "fixtures" / "dextools_pair.html"
PAIR = "https://www.dextools.io/app/ether/pair-explorer/0xaaaa1111"
STAMP = "2026-10-26T09:00:00+00:00"


def test_schema_is_exactly_the_contract() -> None:
    assert ROW_FIELDS == (
        "chain",
        "address",
        "symbol",
        "name",
        "price_usd",
        "liquidity_usd",
        "volume_24h_usd",
        "holders",
        "tax_buy",
        "tax_sell",
        "socials",
        "source_url",
        "fetched_at",
    )


def test_normalize_pair_page() -> None:
    rows = normalize_page(PAIR, FIXTURE.read_text(), fetched_at=STAMP)
    own = rows[0]
    assert (own["chain"], own["address"]) == ("ether", "0xaaaa1111")
    assert own["symbol"] == "PEPE"
    assert own["price_usd"] == 0.00001234
    assert own["liquidity_usd"] == 42_500_000.0
    assert own["volume_24h_usd"] == 9_100_000.0
    assert own["source_url"] == PAIR
    assert own["fetched_at"] == STAMP
    assert "https://t.me/pepecoin" in own["socials"]
    # absent on the page -> null, never guessed
    assert own["holders"] is None
    assert own["tax_buy"] is None
    assert own["tax_sell"] is None


def test_secondary_pair_links_are_null_not_fabricated() -> None:
    rows = normalize_page(PAIR, FIXTURE.read_text(), fetched_at=STAMP)
    others = {row["address"]: row for row in rows[1:]}
    assert set(others) == {"0xbbbb2222"}
    assert others["0xbbbb2222"]["chain"] == "bsc"
    assert all(others["0xbbbb2222"][f] is None for f in ("symbol", "name", "price_usd", "holders"))
