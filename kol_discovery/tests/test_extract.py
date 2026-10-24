"""Extraction tests: token contracts vs wallets, telegram, links, mentions."""

from __future__ import annotations

from kol_discovery.bios import parse_bio

EVM = "0x1111111111111111111111111111111111111111"
SOL = "EYBMFf8mUyvZobqX7bkaCrvZ6bHCYxeVjFHQ9v2bmtAy"


def test_unlabelled_address_is_a_token_contract_not_a_wallet() -> None:
    facts = parse_bio(f"ape into {SOL} and {EVM} now")
    assert SOL in facts.token_contracts
    assert EVM in facts.token_contracts
    assert facts.labelled_wallets == []


def test_labelled_wallet_is_pulled_out_of_contracts() -> None:
    facts = parse_bio(f"wallet: {SOL} | token {EVM}")
    assert facts.labelled_wallets == [SOL]
    assert SOL not in facts.token_contracts
    assert EVM in facts.token_contracts


def test_wallet_labels_variants() -> None:
    for label in ("wallet:", "Wallet =", "sol:", "SOL:", "address:", "evm:"):
        address = SOL if label.casefold().startswith("sol") else EVM
        if label.casefold().startswith("wallet") or label.casefold().startswith("address"):
            address = SOL
        assert parse_bio(f"{label} {address}").labelled_wallets == [address], label


def test_telegram_extraction_dedupes_case_insensitively() -> None:
    facts = parse_bio("t.me/MyChan https://t.me/mychan @someone")
    assert facts.telegrams == ["MyChan"]


def test_links_are_stripped_of_trailing_punctuation() -> None:
    facts = parse_bio("site https://project.xyz. mirrors https://a.io/x,")
    assert "https://project.xyz" in facts.links
    assert "https://a.io/x" in facts.links


def test_mentions_exclude_twitter_urls_and_emails() -> None:
    facts = parse_bio("follow @alpha @beta https://x.com/gamma me@mail.com")
    assert facts.mentions == ["alpha", "beta"]
