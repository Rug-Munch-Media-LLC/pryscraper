"""Hermetic contract: mapping never fabricates, ingest is idempotent, refusals are typed."""

from __future__ import annotations

from pry.datasources.dextools_ingest import pair_to_row, plan
from pry.datasources.dextools_robots import FALLBACK_ROBOTS, robots_verdict
from pry.datasources.dextools_scrape import scrape_dextools
from pry.datasources.dextools_store import DextoolsStore, empty_store_refusal

PAIR = {
    "chain": "arbitrum",
    "token_address": "0x25118290E6A5F4139381D072181157035864099D",
    "token_name": "RAIN / USDT 0.3%",
    "token_symbol": "0.01437804455",
    "liquidity_usd": 2557977.44,
}


class MemoryStore(DextoolsStore):
    """Offline store: same key semantics, no ClickHouse."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[tuple[str, str], dict] = {}

    def count(self) -> int:
        return len(self.rows)

    def latest(self) -> dict[tuple[str, str], dict]:
        return dict(self.rows)

    def insert(self, rows: list[dict]) -> int:
        for row in rows:
            self.rows[(row["chain"], row["address"])] = row
        return len(rows)

    def ensure(self) -> None:
        return None


def test_pair_to_row_derives_symbol_without_fabricating() -> None:
    row = pair_to_row(PAIR, "2026-01-01 00:00:00.000")
    assert row["symbol"] == "RAIN"
    assert row["name"] == "RAIN / USDT 0.3%"  # original kept verbatim
    assert row["quality"] == "symbol_from_name"
    assert row["address"] == "0x25118290e6a5f4139381d072181157035864099d"
    assert row["liquidity_usd"] == 2557977.44
    # Unknown in the source => NULL, never 0 / "" / a guessed URL.
    for field in ("price_usd", "volume_24h_usd", "holders", "tax_buy", "tax_sell", "source_url"):
        assert row[field] is None, field
    assert row["socials"] == []


def test_pair_to_row_never_puts_a_price_in_symbol() -> None:
    row = pair_to_row({**PAIR, "token_name": "RAIN", "token_symbol": "0.0143"})
    assert row["symbol"] is None
    assert row["quality"] == "symbol_is_price"


def test_pair_to_row_keeps_a_real_ticker() -> None:
    row = pair_to_row({**PAIR, "token_symbol": "PEPE"})
    assert (row["symbol"], row["quality"]) == ("PEPE", "ok")


def test_ingest_is_idempotent() -> None:
    store = MemoryStore()
    rows = [pair_to_row(PAIR), pair_to_row({**PAIR, "token_address": "0xbb"})]
    assert store.insert(plan(rows, store.latest())) == 2
    assert store.count() == 2
    assert plan(rows, store.latest()) == []  # same snapshot re-ingested => nothing
    assert store.count() == 2


def test_plan_keeps_one_row_per_key_at_highest_liquidity() -> None:
    low = pair_to_row({**PAIR, "liquidity_usd": 1.0})
    high = pair_to_row({**PAIR, "liquidity_usd": 9.0})
    fresh = plan([low, high], {})
    assert len(fresh) == 1
    assert fresh[0]["liquidity_usd"] == 9.0


def test_robots_refusal_is_typed_and_precedes_network() -> None:
    verdict = robots_verdict("https://www.dextools.io/api/core/search/pool?q=rain", FALLBACK_ROBOTS)
    assert verdict is not None
    assert verdict.code == "blocked.robots"
    assert verdict.to_dict()["error"] == "refused"
    assert robots_verdict("https://www.dextools.io/app/en/ether/newpairs", FALLBACK_ROBOTS) is None


def test_scrape_refuses_blocked_robots_without_fetching() -> None:
    calls: list[str] = []

    def renderer(url: str, timeout_ms: int) -> str:
        calls.append(url)
        raise AssertionError("disallowed path must not be fetched")

    summary = scrape_dextools(
        ["https://www.dextools.io/api/core/search/pool?q=rain"],
        store=MemoryStore(),
        renderer=renderer,
    )
    assert calls == []
    assert summary["ingested"] == 0
    assert [refusal["code"] for refusal in summary["refusals"]] == ["blocked.robots"]


def test_scrape_reports_blocked_measurement_when_page_has_no_data() -> None:
    shell = "<html><head><title>Dextools</title></head><body><div id='__next'></div></body></html>"
    summary = scrape_dextools(
        ["https://www.dextools.io/app/en/ether/newpairs"],
        store=MemoryStore(),
        renderer=lambda url, timeout_ms: shell,
    )
    assert summary["ingested"] == 0
    assert summary["refusals"][0]["code"] == "blocked.measurement"


def test_empty_store_refusal_is_typed() -> None:
    refusal = empty_store_refusal(MemoryStore())
    assert refusal["error"] == "refused"
    assert refusal["code"] == "unavailable"
    assert "ingest" in refusal["reason"]
