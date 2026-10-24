"""Wallet attribution is explicit-only — the central refusal contract."""

from __future__ import annotations

import pytest

from kol_discovery.feeds import account_from_bio_row
from kol_discovery.models import InvalidAddress, KolAccount, UnstatedWalletError, WalletClaim
from kol_discovery.registry import Registry
from kol_discovery.wallets import claim_from_bio, claim_from_leaderboard, merge_claims

SOL = "EYBMFf8mUyvZobqX7bkaCrvZ6bHCYxeVjFHQ9v2bmtAy"
SOL2 = "3BEtHGzhdWPtxSzqVsBorWpbi4jfMvD5cCZy1Qrtac7E"
EVM = "0x1111111111111111111111111111111111111111"


def test_declared_claim_keeps_the_verbatim_statement() -> None:
    claim = claim_from_bio(f"my sol: {SOL}", SOL)
    assert claim.attribution == "declared"
    assert claim.is_fact is True
    assert "sol:" in claim.evidence.lower()


def test_unstated_wallet_is_refused() -> None:
    """A bare address in a bio is a shilled token contract, not a wallet."""
    with pytest.raises(UnstatedWalletError):
        claim_from_bio(f"ape {SOL}", SOL)


def test_wallet_absent_from_bio_is_refused() -> None:
    with pytest.raises(UnstatedWalletError):
        claim_from_bio(f"wallet: {SOL}", SOL2)


def test_leaderboard_claim_is_inferred_never_factual() -> None:
    claim = claim_from_leaderboard(SOL, "https://kolscan.io/leaderboard", "merky")
    assert claim.attribution == "inferred"
    assert claim.is_fact is False
    assert claim.evidence_url.endswith("/leaderboard")


def test_leaderboard_claim_needs_a_fetched_url() -> None:
    with pytest.raises(UnstatedWalletError):
        claim_from_leaderboard(SOL, "  ", "merky")


def test_factual_claim_without_evidence_cannot_be_constructed() -> None:
    with pytest.raises(UnstatedWalletError):
        WalletClaim(chain="solana", address=SOL, source="bio", attribution="declared", evidence="")


def test_claim_rejects_chain_mismatch() -> None:
    with pytest.raises(InvalidAddress, match="not a evm address"):
        WalletClaim(chain="evm", address=SOL, source="bio", attribution="declared", evidence="x")


def test_merge_prefers_statement_over_guess() -> None:
    guess = claim_from_leaderboard(SOL, "https://kolscan.io/leaderboard", "merky")
    stated = claim_from_bio(f"wallet: {SOL}", SOL)
    merged = merge_claims([guess], stated)
    assert len(merged) == 1
    assert merged[0].is_fact is True
    kept = merge_claims(
        [stated], claim_from_leaderboard(SOL, "https://kolscan.io/leaderboard", "merky")
    )
    assert len(kept) == 1
    assert kept[0].is_fact is True, "never downgrade a statement to a guess"


def test_registry_refuses_silent_attachment() -> None:
    registry = Registry()
    registry.add(KolAccount(platform="x", handle="promoking", bio=f"ape {SOL}"))
    with pytest.raises(UnstatedWalletError):
        registry.attach_wallet("x:promoking", claim_from_bio(f"ape {SOL}", SOL))


def test_bio_row_with_unlisted_wallet_drops_it_instead_of_guessing() -> None:
    row = {
        "handle": "Someone",
        "bio": f"ape {SOL}",
        "declared_wallets": [SOL],
    }
    account = account_from_bio_row(row)
    assert account.wallets == []


def test_bio_row_with_stated_wallet_keeps_it() -> None:
    row = {"handle": "Someone", "bio": f"wallet: {EVM}", "declared_wallets": [EVM]}
    account = account_from_bio_row(row)
    assert len(account.wallets) == 1
    assert account.wallets[0].attribution == "declared"
