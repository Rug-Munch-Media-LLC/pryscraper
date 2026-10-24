"""Registry records and stable keys.

Stable key rules (dedupe is enforced on these, case-insensitively):
  * account -> ``<platform>:<handle.casefold()>``
  * wallet  -> ``<chain>:<address.casefold()>``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "kol-discovery/1"

Attribution = Literal["declared", "verified", "inferred"]

#: Only these may ever be presented as fact.
FACTUAL_ATTRIBUTIONS: frozenset[str] = frozenset({"declared", "verified"})

_ADDRESS_RE = {
    "solana": re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"),
    "evm": re.compile(r"^0x[0-9a-fA-F]{40}$"),
}


class InvalidAddress(ValueError):
    """Address does not match any supported chain format."""


class UnstatedWalletError(ValueError):
    """A wallet was offered without a statement saying it belongs to the KOL."""


def normalize_handle(handle: str) -> str:
    """Lowercase, strip ``@`` and any profile URL prefix."""
    value = (handle or "").strip()
    value = re.sub(r"^https?://(?:www\.)?(?:x|twitter)\.com/", "", value, flags=re.I)
    return value.lstrip("@").split("/")[0].strip().casefold()


def detect_chain(address: str) -> str:
    """Return ``solana`` / ``evm``; raise :class:`InvalidAddress` otherwise."""
    candidate = (address or "").strip()
    for chain, pattern in _ADDRESS_RE.items():
        if pattern.match(candidate):
            return chain
    raise InvalidAddress(f"unsupported address format: {address!r}")


@dataclass(frozen=True)
class WalletClaim:
    """One wallet<->KOL binding, with the statement that justifies it."""

    chain: str
    address: str
    source: str  # bio | pinned | website | leaderboard
    attribution: Attribution
    evidence: str  # literal text that states the binding
    evidence_url: str = ""

    def __post_init__(self) -> None:
        if self.attribution not in ("declared", "verified", "inferred"):
            raise ValueError(f"bad attribution: {self.attribution}")
        if self.attribution in FACTUAL_ATTRIBUTIONS and not self.evidence.strip():
            raise UnstatedWalletError("factual wallet claim needs a verbatim statement")
        if detect_chain(self.address) != self.chain:
            raise InvalidAddress(f"{self.address} is not a {self.chain} address")

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.address.casefold()}"

    @property
    def is_fact(self) -> bool:
        return self.attribution in FACTUAL_ATTRIBUTIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "address": self.address,
            "source": self.source,
            "attribution": self.attribution,
            "evidence": self.evidence,
            "evidence_url": self.evidence_url,
        }


@dataclass
class KolAccount:
    """One KOL account row. ``wallets`` holds fact and non-fact claims alike."""

    platform: str
    handle: str
    display_name: str = ""
    followers: int = 0
    bio: str = ""
    bio_links: list[str] = field(default_factory=list)
    wallets: list[WalletClaim] = field(default_factory=list)
    telegram: str = ""
    projects: list[str] = field(default_factory=list)
    promo_history: list[dict[str, Any]] = field(default_factory=list)
    risk_signals: dict[str, float] = field(default_factory=dict)
    risk_score: float = 0.0
    confidence: float = 0.0
    first_seen: str = ""
    last_checked: str = ""
    sources: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.platform}:{normalize_handle(self.handle)}"

    @property
    def declared_wallets(self) -> list[WalletClaim]:
        """Only bindings the source actually stated."""
        return [w for w in self.wallets if w.is_fact]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "handle": self.handle,
            "display_name": self.display_name,
            "platform": self.platform,
            "followers": self.followers,
            "bio": self.bio,
            "bio_links": list(self.bio_links),
            "wallets": [w.to_dict() for w in self.wallets],
            "telegram": self.telegram,
            "projects": list(self.projects),
            "first_seen": self.first_seen,
            "last_checked": self.last_checked,
            "promo_history": list(self.promo_history),
            "risk_signals": dict(self.risk_signals),
            "risk_score": round(self.risk_score, 3),
            "confidence": round(self.confidence, 3),
            "sources": list(self.sources),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KolAccount:
        wallets = [
            WalletClaim(
                chain=w["chain"],
                address=w["address"],
                source=w.get("source", "bio"),
                attribution=w.get("attribution", "declared"),
                evidence=w.get("evidence", ""),
                evidence_url=w.get("evidence_url", ""),
            )
            for w in data.get("wallets", [])
        ]
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known and k != "wallets"}
        return cls(wallets=wallets, **kwargs)
