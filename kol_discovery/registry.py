"""The registry: one row per account, one row per wallet, deduped hard."""

from __future__ import annotations

import json
from collections.abc import Iterable  # noqa: TC003 - used in a runtime annotation
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION, KolAccount, WalletClaim, normalize_handle
from .wallets import merge_claims


def normalize_watchlist(entries: Iterable[str], platform: str = "x") -> set[str]:
    """Watchlists arrive as handles, ``@handles`` or profile URLs."""
    return {f"{platform}:{normalize_handle(entry)}" for entry in entries if normalize_handle(entry)}


@dataclass
class AddResult:
    key: str
    status: str  # added | merged | skipped_watched
    reason: str = ""


@dataclass
class Registry:
    """In-memory registry; ``watchlist`` holds keys owned by other lanes."""

    accounts: dict[str, KolAccount] = field(default_factory=dict)
    wallet_index: dict[str, str] = field(default_factory=dict)
    watchlist: set[str] = field(default_factory=set)
    sources: list[dict[str, Any]] = field(default_factory=list)

    # ---------------------------------------------------------------- accounts
    def add(self, account: KolAccount) -> AddResult:
        key = account.key
        if key in self.watchlist:
            return AddResult(key, "skipped_watched", "already owned by x-social-ops watchlist")
        existing = self.accounts.get(key)
        if existing is None:
            self.accounts[key] = account
            for claim in account.wallets:
                self.wallet_index.setdefault(claim.key, key)
            return AddResult(key, "added")
        _merge(existing, account)
        for claim in account.wallets:
            self.wallet_index.setdefault(claim.key, key)
        return AddResult(key, "merged")

    def get(self, key: str) -> KolAccount | None:
        return self.accounts.get(key)

    def owner_of_wallet(self, wallet_key: str) -> str | None:
        return self.wallet_index.get(wallet_key)

    # ----------------------------------------------------------------- wallets
    def attach_wallet(self, key: str, claim: WalletClaim) -> bool:
        """Attach a claim; refuses silence. Returns True when it was added."""
        account = self.accounts.get(key)
        if account is None:
            raise KeyError(f"unknown account: {key}")
        owner = self.wallet_index.get(claim.key)
        if owner is not None and owner != key:
            raise ValueError(f"wallet {claim.key} already belongs to {owner}")
        before = len(account.wallets)
        account.wallets = merge_claims(account.wallets, claim)
        self.wallet_index[claim.key] = key
        return len(account.wallets) != before or claim.key in self.wallet_index

    # -------------------------------------------------------------- serializing
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sources": list(self.sources),
            "stats": self.stats(),
            "accounts": [a.to_dict() for a in sorted(self.accounts.values(), key=lambda a: a.key)],
            "wallets": dict(sorted(self.wallet_index.items())),
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> Registry:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        registry = cls(sources=list(data.get("sources", [])))
        for row in data.get("accounts", []):
            account = KolAccount.from_dict(row)
            registry.accounts[account.key] = account
            for claim in account.wallets:
                registry.wallet_index.setdefault(claim.key, account.key)
        return registry

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        accounts = list(self.accounts.values())
        factual = [w for a in accounts for w in a.wallets if w.is_fact]
        inferred = [w for a in accounts for w in a.wallets if not w.is_fact]
        by_platform: dict[str, int] = {}
        for account in accounts:
            by_platform[account.platform] = by_platform.get(account.platform, 0) + 1
        return {
            "accounts": len(accounts),
            "by_platform": dict(sorted(by_platform.items())),
            "wallets_declared": len(factual),
            "wallets_inferred": len(inferred),
            "unique_wallets": len({w.key for w in factual} | {w.key for w in inferred}),
            "with_telegram": sum(1 for a in accounts if a.telegram),
        }


def _merge(target: KolAccount, incoming: KolAccount) -> None:
    """Union merge that never loses a statement and never duplicates a source."""
    target.display_name = target.display_name or incoming.display_name
    target.followers = max(target.followers, incoming.followers)
    target.bio = target.bio or incoming.bio
    target.telegram = target.telegram or incoming.telegram
    target.first_seen = min(filter(None, [target.first_seen, incoming.first_seen]), default="")
    target.last_checked = max(
        filter(None, [target.last_checked, incoming.last_checked]), default=""
    )
    target.confidence = max(target.confidence, incoming.confidence)
    for name in ("bio_links", "projects", "sources"):
        merged = getattr(target, name)
        for value in getattr(incoming, name):
            if value.casefold() not in {v.casefold() for v in merged}:
                merged.append(value)
    for claim in incoming.wallets:
        target.wallets = merge_claims(target.wallets, claim)
    for name, value in incoming.risk_signals.items():
        target.risk_signals.setdefault(name, value)
    target.risk_score = max(target.risk_score, incoming.risk_score)
