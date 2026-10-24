"""kolscan client: fixture parsing, bounded cap, cache, error path (fake HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from kol_discovery.kolscan import KolscanClient, parse_leaderboard

HTML = (Path(__file__).parent / "fixtures" / "kolscan_excerpt.html").read_text(encoding="utf-8")


@dataclass
class FakeResponse:
    status_code: int
    text: str


@dataclass
class FakeHttp:
    status_code: int = 200
    body: str = HTML
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, headers: dict | None = None) -> FakeResponse:
        self.calls.append(url)
        return FakeResponse(self.status_code, self.body)


@dataclass
class FakeClock:
    value: float = 1_000.0
    step: float = 1.0

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def test_parse_keeps_real_records_and_dedupes_case_variants() -> None:
    accounts, wallet_only = parse_leaderboard(HTML)
    handles = [account.handle.casefold() for account in accounts]
    assert handles == [
        "kennyloaded",
        "padreprints",
        "merkytrades",
        "stormstrades",
        "barakatrades",
    ]
    assert wallet_only == 1, "twitter:null row is not turned into an account"


def test_parsed_wallets_are_inferred_not_declared() -> None:
    accounts, _ = parse_leaderboard(HTML)
    for account in accounts:
        assert account.wallets, account.handle
        claim = account.wallets[0]
        assert claim.attribution == "inferred"
        assert claim.is_fact is False
        assert claim.evidence_url.endswith("/leaderboard")


def test_parsed_records_carry_names() -> None:
    accounts, _ = parse_leaderboard(HTML)
    names = {account.handle.casefold(): account.display_name for account in accounts}
    assert names["kennyloaded"] == "KennyLoaded"
    assert names["merkytrades"] == "merky"


def test_empty_or_garbage_html_returns_nothing() -> None:
    assert parse_leaderboard("") == ([], 0)
    assert parse_leaderboard("<html>login required</html>") == ([], 0)


def test_limit_is_a_hard_cap() -> None:
    accounts, _ = KolscanClient(http=FakeHttp(), clock=FakeClock()).fetch(limit=2)
    assert len(accounts) == 2


def test_second_fetch_uses_cache() -> None:
    http = FakeHttp()
    client = KolscanClient(http=http, clock=FakeClock())
    client.fetch(limit=10)
    client.fetch(limit=10)
    assert len(http.calls) == 1


def test_non_200_raises_instead_of_returning_fake_rows() -> None:
    with pytest.raises(RuntimeError, match="403"):
        KolscanClient(http=FakeHttp(status_code=403), clock=FakeClock()).fetch(limit=5)
