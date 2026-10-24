"""Dedupe: one row per account/wallet across every source, case-insensitive."""

from __future__ import annotations

import pytest

from kol_discovery.models import KolAccount, normalize_handle
from kol_discovery.registry import Registry, normalize_watchlist
from kol_discovery.wallets import claim_from_bio, claim_from_leaderboard

SOL = "EYBMFf8mUyvZobqX7bkaCrvZ6bHCYxeVjFHQ9v2bmtAy"
EVM = "0x1111111111111111111111111111111111111111"


def test_normalize_handle_strips_at_and_url() -> None:
    assert normalize_handle("@Merky") == "merky"
    assert normalize_handle("https://x.com/MerkyTrades/") == "merkytrades"
    assert normalize_handle("  MERKY ") == "merky"


def test_case_variants_collapse_to_one_row() -> None:
    registry = Registry()
    registry.add(KolAccount(platform="x", handle="KennyLoaded"))
    result = registry.add(KolAccount(platform="x", handle="kennyLOADED"))
    assert result.status == "merged"
    assert len(registry.accounts) == 1


def test_two_sources_merge_without_duplicating() -> None:
    registry = Registry()
    registry.add(
        KolAccount(platform="x", handle="merky", sources=["kolscan_leaderboard"], followers=10)
    )
    registry.add(
        KolAccount(
            platform="x", handle="Merky", sources=["bio_capture"], followers=99, telegram="merkytg"
        )
    )
    row = registry.accounts["x:merky"]
    assert row.followers == 99
    assert row.telegram == "merkytg"
    assert sorted(row.sources) == ["bio_capture", "kolscan_leaderboard"]
    assert len(registry.accounts) == 1


def test_wallet_attached_twice_is_not_duplicated() -> None:
    registry = Registry()
    registry.add(KolAccount(platform="x", handle="merk ", bio=f"wallet: {SOL}"))
    claim = claim_from_bio(f"wallet: {SOL}", SOL)
    registry.attach_wallet("x:merk", claim)
    registry.attach_wallet("x:merk", claim)
    assert len(registry.accounts["x:merk"].wallets) == 1
    assert len(registry.wallet_index) == 1


def test_same_wallet_cannot_belong_to_two_accounts() -> None:
    registry = Registry()
    registry.add(KolAccount(platform="x", handle="a"))
    registry.add(KolAccount(platform="x", handle="b"))
    registry.attach_wallet(
        "x:a", claim_from_leaderboard(SOL, "https://kolscan.io/leaderboard", "a")
    )
    with pytest.raises(ValueError, match="already belongs to"):
        registry.attach_wallet(
            "x:b", claim_from_leaderboard(SOL, "https://kolscan.io/leaderboard", "b")
        )


def test_watchlist_entries_are_skipped_not_duplicated() -> None:
    watchlist = normalize_watchlist(["@Merky", "https://x.com/KennyLoaded"])
    registry = Registry(watchlist=watchlist)
    assert registry.add(KolAccount(platform="x", handle="MERKY")).status == "skipped_watched"
    assert registry.add(KolAccount(platform="x", handle="kennyLOADED")).status == "skipped_watched"
    assert registry.add(KolAccount(platform="x", handle="newguy")).status == "added"
    assert list(registry.accounts) == ["x:newguy"]


def test_wallet_index_survives_round_trip() -> None:
    registry = Registry()
    registry.add(KolAccount(platform="x", handle="miro", bio=f"wallet: {EVM}"))
    registry.attach_wallet("x:miro", claim_from_bio(f"wallet: {EVM}", EVM))
    restored = Registry.load(_save(registry))
    assert restored.owner_of_wallet(f"solana:{SOL}") is None
    assert restored.owner_of_wallet(f"evm:{EVM.casefold()}") == "x:miro"
    assert restored.stats()["wallets_declared"] == 1


def _save(registry: Registry):
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "reg.json"
    registry.save(path)
    return path
